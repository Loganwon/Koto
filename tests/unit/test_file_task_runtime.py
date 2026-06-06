import json

import pytest

from app.core.agent.file_task_contract import (
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskLedger,
    FileTaskRequest,
    FileTaskToolStreamChunk,
    FileTaskToolStreamResult,
    event_to_sse,
)
from app.core.agent.file_task_runtime import FileTaskRuntime
from app.core.agent.file_task_model import FileTaskModelClient
from app.core.agent.file_task_tool_catalog import file_task_tool_specs, supported_file_workflows
from app.core.agent.file_task_tool_gateway import FileTaskToolContext, FileTaskToolGateway


def test_file_task_runtime_routes_pdf_docx_review_to_doc_annotate_bridge(monkeypatch):
    import app.core.agent.file_task_doc_annotate_bridge as bridge

    captured = {}

    def fake_stream(request, *, workspace_root="", gemini_client=None):
        captured["request"] = request
        captured["workspace_root"] = workspace_root
        captured["gemini_client"] = gemini_client
        ledger = FileTaskLedger(request.run_id)
        yield ledger.event(
            "run.started",
            {
                "task": request.task,
                "mode": "doc_annotate_bridge",
                "target_path": "interview.docx",
                "source_path": "source.pdf",
            },
            step_id="run",
        )
        yield ledger.event(
            "run.finished",
            {
                "summary": "已切入 DOCX 审校批注桥接流程。",
                "completed_task": True,
                "mode": "doc_annotate_bridge",
            },
            step_id="run",
        )

    monkeypatch.setattr(bridge, "stream_request", fake_stream)

    def unexpected_executor(tool_name, args):
        raise AssertionError(f"generic tool loop should not run: {tool_name}")

    def unexpected_model(**kwargs):
        raise AssertionError("generic model loop should not run")

    runtime = FileTaskRuntime(
        tool_executor=unexpected_executor,
        model_client=unexpected_model,
        workspace_root="C:/runtime-workspace",
        gemini_client="gemini-client",
        max_rounds=2,
    )
    request = FileTaskRequest(
        task="PDF是原文，docx文件是现有翻译稿。根据原文内容，润色翻译稿的语句并标注出来。",
        run_id="annotate_runtime",
        target_path="interview.docx",
        files=[
            FileTaskFile(path="source.pdf", name="source.pdf", type="pdf"),
            FileTaskFile(path="interview.docx", name="interview.docx", type="docx", target=True),
        ],
    )

    events = list(runtime.run(request))

    assert captured["request"] is request
    assert captured["workspace_root"] == "C:/runtime-workspace"
    assert captured["gemini_client"] == "gemini-client"
    plan_checked = next(event for event in events if event.type == "plan.checked")
    assert plan_checked.payload["passed"] is True
    assert plan_checked.payload["routing"] == "doc_annotate_bridge"
    run_started = next(event for event in events if event.type == "run.started")
    assert run_started.payload["mode"] == "doc_annotate_bridge"
    assert events[-1].payload["completed_task"] is True


def test_file_task_runtime_relays_streaming_tool_events_before_tool_finished():
    def fake_executor(tool_name, args):
        assert tool_name == "write_docx_content"
        return FileTaskToolStreamResult(
            chunks=[
                FileTaskToolStreamChunk(
                    kind="event",
                    event_type="step_progress",
                    payload={
                        "detail": "已写入 1/3 段落",
                        "progress": 33,
                        "level": "progress",
                        "file_updated": True,
                        "path": "draft.docx",
                        "file_path": "draft.docx",
                        "supported": True,
                    },
                ),
                FileTaskToolStreamChunk(
                    kind="result",
                    payload={
                        "success": True,
                        "path": "draft.docx",
                        "file_path": "draft.docx",
                        "file_type": "docx",
                        "operation": "write_docx_content",
                        "summary": "已将 3 段改写写回 draft.docx。",
                        "preview": "已写入 3 段",
                        "change_type": "rewrite",
                        "focus": True,
                    },
                ),
            ]
        )

    def fake_model(**kwargs):
        return {
            "content": "开始改写",
            "tool_calls": [
                {
                    "id": "write_demo",
                    "name": "write_docx_content",
                    "args": {"path": "draft.docx", "paragraphs": '[{"text":"改写后的内容"}]'},
                }
            ],
        }

    request = FileTaskRequest(
        task="将文档的第一段改写后写回",
        run_id="stream_tool_demo",
        target_path="draft.docx",
        files=[FileTaskFile(path="draft.docx", name="draft.docx", type="docx", target=True)],
    )

    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model, max_rounds=1).run(request))

    progress_index = next(i for i, event in enumerate(events) if event.type == "step_progress")
    tool_finished_index = next(
        i for i, event in enumerate(events) if event.type == "tool.finished" and event.payload.get("tool_name") == "write_docx_content"
    )
    file_changed = next(event for event in events if event.type == "file.changed")

    assert progress_index < tool_finished_index
    assert events[progress_index].payload["file_updated"] is True
    assert events[progress_index].payload["path"] == "draft.docx"
    assert file_changed.payload["path"] == "draft.docx"


def test_file_task_runtime_routes_single_docx_annotation_to_doc_annotate_bridge(monkeypatch):
    import app.core.agent.file_task_doc_annotate_bridge as bridge

    captured = {}

    def fake_stream(request, *, workspace_root="", gemini_client=None):
        captured["request"] = request
        captured["workspace_root"] = workspace_root
        captured["gemini_client"] = gemini_client
        ledger = FileTaskLedger(request.run_id)
        yield ledger.event(
            "run.started",
            {
                "task": request.task,
                "mode": "doc_annotate_bridge",
                "target_path": "interview.docx",
            },
            step_id="run",
        )
        yield ledger.event(
            "run.finished",
            {
                "summary": "已切入单 DOCX 审校批注桥接流程。",
                "completed_task": True,
                "mode": "doc_annotate_bridge",
            },
            step_id="run",
        )

    monkeypatch.setattr(bridge, "stream_request", fake_stream)

    def unexpected_executor(tool_name, args):
        raise AssertionError(f"generic tool loop should not run: {tool_name}")

    def unexpected_model(**kwargs):
        raise AssertionError("generic model loop should not run")

    request = FileTaskRequest(
        task="将你觉得写得不好的地方批注出来",
        run_id="single_docx_generic_demo",
        target_path="interview.docx",
        files=[FileTaskFile(path="interview.docx", name="interview.docx", type="docx", target=True)],
    )

    events = list(FileTaskRuntime(tool_executor=unexpected_executor, model_client=unexpected_model, max_rounds=2).run(request))

    assert captured["request"] is request
    assert captured["workspace_root"] == ""
    assert captured["gemini_client"] is None
    plan_checked = next(event for event in events if event.type == "plan.checked")
    assert plan_checked.payload["passed"] is True
    assert plan_checked.payload["routing"] == "doc_annotate_bridge"
    run_started = next(event for event in events if event.type == "run.started")
    assert run_started.payload["mode"] == "doc_annotate_bridge"
    assert events[-1].payload["completed_task"] is True
    assert events[-1].payload["summary"] == "已切入单 DOCX 审校批注桥接流程。"


def test_file_task_runtime_does_not_external_fallback_after_doc_annotate_bridge_failure(monkeypatch):
    import app.core.agent.file_task_doc_annotate_bridge as bridge

    def fake_stream(request, *, workspace_root="", gemini_client=None):
        ledger = FileTaskLedger(request.run_id)
        yield ledger.event(
            "run.started",
            {
                "task": request.task,
                "mode": "doc_annotate_bridge",
                "target_path": "interview.docx",
            },
            step_id="run",
        )
        yield ledger.event(
            "run.finished",
            {
                "summary": "Word 原生修订写回未完成。",
                "completed_task": False,
                "mode": "doc_annotate_bridge",
                "runtime": {"terminal_status": "needs_attention"},
            },
            step_id="run",
        )

    monkeypatch.setattr(bridge, "stream_request", fake_stream)

    class FakeModelClient:
        def __init__(self):
            self.options_seen = []

        def fallback_planner_backend_for_request(self, request):
            return "hermes"

        def call(self, **kwargs):
            request = kwargs["request"]
            messages = kwargs["messages"]
            self.options_seen.append(dict(request.options or {}))

            if any(message.get("role") == "function" and message.get("name") == "annotate_file" for message in messages):
                return {
                    "content": "Hermes 已完成批注写回。",
                    "tool_calls": [],
                    "_planner": {
                        "backend": "hermes",
                        "source": "external",
                        "policy": "explicit_backend",
                        "transport": "embedded",
                        "reason": str(request.options.get("planner_runtime_reason") or ""),
                    },
                }

            return {
                "content": "Hermes 重新规划并执行批注写回。",
                "tool_calls": [
                    {
                        "id": "hermes_annotate_docx",
                        "name": "annotate_file",
                        "args": {
                            "path": "interview.docx",
                            "annotations": "[]",
                            "requirement": "将你觉得写得不好的地方批注出来",
                        },
                    }
                ],
                "_planner": {
                    "backend": "hermes",
                    "source": "external",
                    "policy": "explicit_backend",
                    "transport": "embedded",
                    "reason": str(request.options.get("planner_runtime_reason") or ""),
                },
            }

    def fake_executor(tool_name, args):
        if tool_name == "annotate_file":
            return json.dumps(
                {
                    "success": True,
                    "path": args["path"],
                    "file_path": args["path"],
                    "file_type": "docx",
                    "operation": "annotate_file",
                    "summary": "已写入 1 条批注。",
                    "change_type": "annotate",
                    "annotations_added": 1,
                    "focus": True,
                },
                ensure_ascii=False,
            )
        if tool_name == "verify_task_completion":
            return json.dumps(
                {
                    "completed": True,
                    "summary": "interview.docx 已完成更新。",
                    "confidence": 0.95,
                },
                ensure_ascii=False,
            )
        raise AssertionError(f"unexpected tool call: {tool_name}")

    model_client = FakeModelClient()
    request = FileTaskRequest(
        task="将你觉得写得不好的地方批注出来",
        run_id="doc_annotate_bridge_external_fallback_demo",
        target_path="interview.docx",
        files=[FileTaskFile(path="interview.docx", name="interview.docx", type="docx", content="正文", target=True)],
    )

    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=model_client, max_rounds=4).run(request))

    run_finished = next(event for event in reversed(events) if event.type == "run.finished")

    assert any(event.payload.get("mode") == "doc_annotate_bridge" for event in events if event.type == "run.started")
    assert run_finished.payload.get("mode") == "doc_annotate_bridge"
    assert run_finished.payload["completed_task"] is False
    assert not any(event.type == "planner.selected" for event in events)
    assert not any(event.type == "planner.fallback" for event in events)
    assert model_client.options_seen == []


@pytest.mark.parametrize("task_text", [
    "取消docx里面所有批注",
    "将docx里面的标注都移除",
])
def test_doc_annotate_bridge_does_not_route_docx_clear_comment_requests(task_text):
    import app.core.agent.file_task_doc_annotate_bridge as bridge

    request = FileTaskRequest(
        task=task_text,
        run_id="clear_docx_comments_demo",
        target_path="interview.docx",
        files=[FileTaskFile(path="interview.docx", name="interview.docx", type="docx", target=True)],
    )

    assert bridge.looks_like_docx_review_clear_request(request.task) is True
    assert bridge.should_route_request(request) is False


@pytest.mark.parametrize("task_text", [
    "取消docx里面所有批注",
    "将docx里面的标注都移除",
])
def test_file_task_runtime_classifies_docx_clear_comment_request_as_write_not_annotation(task_text):
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {"content": "ok", "tool_calls": []})
    request = FileTaskRequest(
        task=task_text,
        run_id="clear_docx_comments_classification",
        target_path="interview.docx",
        files=[FileTaskFile(path="interview.docx", name="interview.docx", type="docx", target=True)],
    )

    classification = runtime._classify_request(request, request.files)

    assert runtime._is_docx_annotation_request(request) is False
    assert classification.docx_annotation_request is False
    assert classification.write_intent is True
    assert classification.output_mode == "write"
    assert classification.task_family == "transform"
    assert classification.operation_kind == "write"
    assert "clear_docx_review_marks" in classification.matched_capabilities
    assert "annotate_file" not in classification.matched_capabilities


def test_file_task_runtime_treats_awaiting_confirmation_tool_result_as_paused_state():
    artifact = {
        "artifact_type": "koto_large_task_resume_v1",
        "category": "batch_confirmation",
        "title": "继续执行第 1/3 批",
        "summary": "文件较大，等待确认开始第 1/3 批。",
        "suggested_next_step": "确认后继续执行第 1/3 批审校。",
    }

    def fake_executor(tool_name, args):
        if tool_name == "parse_file_to_text":
            return "参考内容"
        if tool_name == "annotate_file":
            return FileTaskToolStreamResult(
                chunks=[
                    FileTaskToolStreamChunk(
                        kind="event",
                        event_type="plan.confirmed",
                        payload={
                            "summary": "按 3 批执行",
                            "steps": [{"id": "batch_1", "title": "第 1 批"}],
                        },
                    ),
                    FileTaskToolStreamChunk(
                        kind="result",
                        payload={
                            "success": True,
                            "summary": "文件较大，已生成 3 批执行计划，等待确认开始第 1/3 批。",
                            "awaiting_confirmation": True,
                            "target_path": "translation.docx",
                            "source_path": "source.pdf",
                            "batch_index": 0,
                            "total_batches": 3,
                            "next_action_artifact": artifact,
                        },
                    ),
                ]
            )
        raise AssertionError(f"unexpected tool call: {tool_name}")

    def fake_model(**kwargs):
        if any(message.get("role") == "function" and message.get("name") == "annotate_file" for message in kwargs["messages"]):
            return {"content": "等待确认后继续", "tool_calls": []}
        return {
            "content": "开始分批审校",
            "tool_calls": [
                {
                    "id": "annotate_batch_demo",
                    "name": "annotate_file",
                    "args": {
                        "path": "translation.docx",
                        "requirement": "PDF是原文，docx文件是现有翻译稿。文件较大，请拆成多个分段来处理。",
                        "annotations": "[]",
                    },
                }
            ],
        }

    request = FileTaskRequest(
        task="PDF是原文，docx文件是现有翻译稿。文件较大，请拆成多个分段来处理。",
        run_id="annotate_wait_confirm",
        target_path="translation.docx",
        files=[
            FileTaskFile(path="source.pdf", name="source.pdf", type="pdf"),
            FileTaskFile(path="translation.docx", name="translation.docx", type="docx", target=True),
        ],
    )

    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model, max_rounds=2).run(request))

    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert any(event.type == "plan.confirmed" for event in events)
    assert not any(event.type == "tool.finished" and event.payload.get("tool_name") == "write_guard" for event in events)
    assert check_finished.payload["status"] == "awaiting_confirmation"
    assert check_finished.payload["next_action_artifact"] == artifact
    assert run_finished.payload["completed_task"] is False
    assert run_finished.payload["next_action_artifact"] == artifact


def test_file_task_runtime_stops_retrying_when_write_target_is_locked():
    model_calls = {"count": 0}

    def fake_model(**kwargs):
        model_calls["count"] += 1
        return {
            "content": "先把 Excel 表格写入目标 Word。",
            "tool_calls": [
                {
                    "id": "insert_locked_demo",
                    "name": "insert_excel_as_docx_table",
                    "args": {
                        "source_path": "financial-model.xlsx",
                        "target_path": "report.docx",
                        "sheet_name": "P&L",
                    },
                }
            ],
        }

    def fake_executor(tool_name, args):
        if tool_name == "parse_file_to_text":
            return f"内容来自 {args['path']}"
        if tool_name == "insert_excel_as_docx_table":
            return json.dumps(
                {
                    "success": False,
                    "path": args["target_path"],
                    "status": "write_blocked",
                    "summary": "目标文件 report.docx 当前不可写，无法写回原文件。",
                    "error": "目标文件 report.docx 当前不可写，无法写回原文件。",
                    "suggested_next_step": "检查文件权限；如果文件正在被占用，请关闭相关 Koto 页签或其他程序后重试。",
                },
                ensure_ascii=False,
            )
        raise AssertionError(f"unexpected tool call: {tool_name}")

    request = FileTaskRequest(
        task="将 xlsx 财务预测加入 docx",
        run_id="write_locked_demo",
        target_path="report.docx",
        files=[
            FileTaskFile(path="financial-model.xlsx", name="financial-model.xlsx", type="xlsx"),
            FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True),
        ],
    )

    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model, max_rounds=4).run(request))
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = next(event for event in events if event.type == "run.finished")

    assert model_calls["count"] == 1
    assert not any(event.type == "tool.finished" and event.payload.get("tool_name") == "write_guard" for event in events)
    assert not any(event.type == "tool.finished" and event.payload.get("tool_name") == "repair_guard" for event in events)
    assert check_finished.payload["status"] == "write_blocked"
    assert "当前不可写" in check_finished.payload["summary"]
    assert check_finished.payload["remaining"] == ["检查文件权限；如果文件正在被占用，请关闭相关 Koto 页签或其他程序后重试。"]
    assert run_finished.payload["completed_task"] is False
    assert "当前不可写" in run_finished.payload["summary"]


def test_file_task_runtime_keeps_recovery_copy_but_does_not_mark_original_write_complete():
    model_calls = {"count": 0}

    def fake_model(**kwargs):
        model_calls["count"] += 1
        return {
            "content": "先把 Excel 表格写入目标 Word。",
            "tool_calls": [
                {
                    "id": "insert_locked_demo",
                    "name": "insert_excel_as_docx_table",
                    "args": {
                        "source_path": "financial-model.xlsx",
                        "target_path": "report.docx",
                        "sheet_name": "P&L",
                    },
                }
            ],
        }

    def fake_executor(tool_name, args):
        if tool_name == "parse_file_to_text":
            return f"内容来自 {args['path']}"
        if tool_name == "insert_excel_as_docx_table":
            return json.dumps(
                {
                    "success": False,
                    "path": "report.koto-copy.docx",
                    "file_type": "docx",
                    "change_type": "create",
                    "operation": "insert_excel_as_docx_table",
                    "summary": "原目标文件 report.docx 当前不可写，尚未写回原文件；已将工作表“P&L”的 50 行数据写入恢复副本 report.koto-copy.docx",
                    "preview": "收入合计",
                    "status": "write_blocked",
                    "error": "原目标文件 report.docx 当前不可写，尚未写回原文件；已将工作表“P&L”的 50 行数据写入恢复副本 report.koto-copy.docx",
                    "suggested_next_step": "检查 report.docx 的文件权限；如果文件正在被占用，请关闭相关 Koto 页签或其他程序后重新执行写回原文件。",
                    "original_target_path": "report.docx",
                    "blocked_target": True,
                    "blocked_reason": "目标文件 report.docx 当前不可写，无法写回原文件。",
                    "fallback_copy": True,
                    "sheet": "P&L",
                    "rows_written": 50,
                    "columns_written": 13,
                },
                ensure_ascii=False,
            )
        raise AssertionError(f"unexpected tool call: {tool_name}")

    request = FileTaskRequest(
        task="将 xlsx 财务预测加入 docx",
        run_id="write_locked_recovery_copy_demo",
        target_path="report.docx",
        files=[
            FileTaskFile(path="financial-model.xlsx", name="financial-model.xlsx", type="xlsx"),
            FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True),
        ],
    )

    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model, max_rounds=4).run(request))
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = next(event for event in events if event.type == "run.finished")
    file_changed = next(event for event in events if event.type == "file.changed")
    tool_finished = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "insert_excel_as_docx_table"
    )

    assert model_calls["count"] == 1
    assert file_changed.payload["path"] == "report.koto-copy.docx"
    assert file_changed.payload["fallback_copy"] is True
    assert tool_finished.payload["blocked"] is True
    assert not any(event.type == "tool.finished" and event.payload.get("tool_name") == "write_guard" for event in events)
    assert not any(event.type == "tool.finished" and event.payload.get("tool_name") == "repair_guard" for event in events)
    assert check_finished.payload["status"] == "write_blocked"
    assert check_finished.payload["remaining"] == ["检查 report.docx 的文件权限；如果文件正在被占用，请关闭相关 Koto 页签或其他程序后重新执行写回原文件。"]
    assert run_finished.payload["completed_task"] is False
    assert "尚未写回原文件" in run_finished.payload["summary"]
    assert "当前不可写" in run_finished.payload["summary"]


def test_file_task_runtime_emits_typed_event_sequence_with_monotonic_seq():
    def fake_model(**kwargs):
        return {"content": "已总结：alpha beta gamma", "tool_calls": []}

    def fake_executor(tool_name, args):
        assert tool_name == "parse_file_to_text"
        assert args["path"] == "notes.md"
        return "alpha beta gamma"

    request = FileTaskRequest(
        task="总结这个文件",
        run_id="run_demo",
        files=[FileTaskFile(path="notes.md", name="notes.md", type="md")],
    )
    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model).run(request))
    event_types = [event.type for event in events]
    run_started = events[0]

    assert event_types[0] == "run.started"
    assert "task.classified" in event_types
    assert "plan.checked" in event_types
    assert event_types.index("task.classified") < event_types.index("plan.checked")
    assert event_types.index("plan.checked") < event_types.index("plan.created")
    assert event_types.index("plan.created") < event_types.index("step.started")
    assert "tool.started" in event_types
    assert "tool.finished" in event_types
    assert "step.result" in event_types
    assert event_types[-1] == "run.finished"
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert all(event.run_id == "run_demo" for event in events)
    assert run_started.payload["request_kind"] == "new_task"
    assert run_started.payload["task_family"] == "analyze"
    assert run_started.payload["execution_mode"] == "generic_tool_loop"

    finished = next(event for event in events if event.type == "tool.finished")
    step_result_ids = [event.step_id for event in events if event.type == "step.result"]
    execute_result = next(event for event in events if event.type == "step.result" and event.step_id == "execute")
    check_result = next(event for event in events if event.type == "step.result" and event.step_id == "check")

    assert finished.payload["success"] is True
    assert "alpha beta" in finished.payload["result_preview"]
    assert "context" in step_result_ids
    assert "execute" in step_result_ids
    assert "check" in step_result_ids
    assert execute_result.payload["summary"] == "已总结：alpha beta gamma"
    assert check_result.payload["passed"] is True


def test_file_task_runtime_rolls_up_step_results_for_generic_write_tasks():
    def fake_executor(tool_name, args):
        if tool_name == "parse_file_to_text":
            return "第一段\n第二段"
        if tool_name == "write_docx_content":
            return FileTaskToolStreamResult(
                chunks=[
                    FileTaskToolStreamChunk(
                        kind="event",
                        event_type="step_progress",
                        payload={
                            "detail": "已写入 1/2 个段落",
                            "progress": 80,
                            "level": "progress",
                            "file_updated": True,
                            "path": "interview.docx",
                            "file_path": "interview.docx",
                            "supported": True,
                        },
                    ),
                    FileTaskToolStreamChunk(
                        kind="result",
                        payload={
                            "success": True,
                            "path": "interview.docx",
                            "file_path": "interview.docx",
                            "file_type": "docx",
                            "operation": "write_docx_content",
                            "summary": "已将 2 个段落写回 interview.docx。",
                            "preview": "重写了开头两段",
                            "change_type": "modify",
                            "focus": True,
                            "paragraphs_written": 2,
                            "updated_in_place": True,
                        },
                    ),
                ]
            )
        if tool_name == "verify_task_completion":
            return json.dumps({"completed": True, "summary": "已更新 interview.docx。"}, ensure_ascii=False)
        raise AssertionError(f"unexpected tool call: {tool_name}")

    def fake_model(**kwargs):
        if any(message.get("role") == "function" and message.get("name") == "write_docx_content" for message in kwargs["messages"]):
            return {"content": "已完成写回", "tool_calls": []}
        return {
            "content": "开始改写并写回",
            "tool_calls": [
                {
                    "id": "rewrite_docx_demo",
                    "name": "write_docx_content",
                    "args": {
                        "path": "interview.docx",
                        "paragraphs": '[{"text":"重写后的开头第一段"},{"text":"重写后的开头第二段"}]',
                    },
                }
            ],
        }

    request = FileTaskRequest(
        task="把访谈文稿的开头改写后写回文档",
        run_id="step_result_write_demo",
        target_path="interview.docx",
        files=[FileTaskFile(path="interview.docx", name="interview.docx", type="docx", target=True)],
    )

    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model, max_rounds=2).run(request))
    execute_results = [event for event in events if event.type == "step.result" and event.step_id == "execute"]
    check_result = next(event for event in events if event.type == "step.result" and event.step_id == "check")

    assert execute_results
    assert execute_results[-1].payload["status"] == "completed"
    assert execute_results[-1].payload["file_change_count"] == 1
    assert execute_results[-1].payload["file_changes"][0]["path"] == "interview.docx"
    assert check_result.payload["passed"] is True
    assert check_result.payload["status"] == "completed"


def test_file_task_runtime_classifies_resume_requests_before_plan_creation():
    def fake_model(**kwargs):
        return {"content": "等待继续执行", "tool_calls": []}

    request = FileTaskRequest(
        task="继续第 1/3 批",
        run_id="resume_classification_demo",
        target_path="translation.docx",
        files=[
            FileTaskFile(path="source.pdf", name="source.pdf", type="pdf"),
            FileTaskFile(path="translation.docx", name="translation.docx", type="docx", target=True, content="现有译稿"),
        ],
        options={
            "batch_control": {
                "adapter": "doc_annotate_bridge",
                "policy": "confirm_each_batch",
                "batch_index": 0,
                "total_batches": 3,
            }
        },
    )

    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(request))
    event_types = [event.type for event in events]
    classified_index = event_types.index("task.classified")
    plan_checked_index = event_types.index("plan.checked")
    run_started = events[0]
    classified = events[classified_index]

    assert classified_index > 0
    assert plan_checked_index > 0
    assert classified_index < plan_checked_index
    assert run_started.payload["request_kind"] == "resume"
    assert run_started.payload["task_family"] == "annotate"
    assert run_started.payload["execution_mode"] == "awaiting_confirmation_resume"
    assert run_started.payload["docx_annotation_request"] is True
    assert "batch_control_resume" in run_started.payload["reason_codes"]
    assert classified.payload["classification"]["request_kind"] == "resume"
    assert classified.payload["classification"]["task_family"] == "annotate"
    assert classified.payload["classification"]["execution_mode"] == "awaiting_confirmation_resume"
    assert classified.payload["intent_plan"]["intent_type"] == "annotate"


def test_file_task_runtime_readonly_summary_surfaces_model_answer():
    model_answer = "文档摘要：这份文档说明了产品规划、市场竞争和销售预测。"

    def fake_model(**kwargs):
        return {"content": model_answer, "tool_calls": []}

    request = FileTaskRequest(
        task="总结这个文档",
        run_id="summary_demo",
        files=[
            FileTaskFile(
                path="雷鸟访谈问题.docx",
                name="雷鸟访谈问题.docx",
                type="docx",
                content="产品和市场规划。未来产品形态、竞争策略、销售预测。",
            )
        ],
    )
    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(request))
    event_types = [event.type for event in events]
    run_started = events[0]
    plan_created = next(event for event in events if event.type == "plan.created")
    model_message = next(event for event in events if event.payload.get("tool_name") == "model_message")
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert event_types[0] == "run.started"
    assert "task.classified" in event_types
    assert "plan.checked" in event_types
    assert event_types.index("plan.checked") < event_types.index("plan.created")
    assert run_started.payload["output_mode"] == "answer"
    assert plan_created.payload["summary"] == "准备处理 1 个文件。"
    assert model_message.payload["result_preview"] == model_answer
    assert check_finished.payload["passed"] is True
    assert check_finished.payload["summary"] == "已完成只读任务，没有产生文件写入。"
    assert run_finished.payload["summary"] == model_answer
    assert run_finished.payload["completed_task"] is True


def test_file_task_runtime_context_step_keeps_parse_file_to_text_results_as_snippets():
    def fake_executor(tool_name, args):
        if tool_name == "parse_file_to_text":
            return f"内容来自 {args['path']}"
        raise AssertionError(f"unexpected tool call: {tool_name}")

    def fake_model(**kwargs):
        return {"content": "已完成总结。", "tool_calls": []}

    request = FileTaskRequest(
        task="总结这两个文件",
        run_id="context_snippet_parse_demo",
        files=[
            FileTaskFile(path="financial-model.xlsx", name="financial-model.xlsx", type="xlsx"),
            FileTaskFile(path="report.docx", name="report.docx", type="docx"),
        ],
    )

    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model).run(request))
    context_result = next(event for event in events if event.type == "step.result" and event.step_id == "context")

    assert context_result.payload["status"] == "completed"
    assert context_result.payload["snippet_count"] == 2
    assert [item["source"] for item in context_result.payload["snippets"]] == [
        "financial-model.xlsx",
        "report.docx",
    ]
    assert context_result.payload["snippets"][0]["preview"].startswith("内容来自 financial-model.xlsx")


def test_file_task_runtime_readonly_model_unavailable_summarizes_explicit_context():
    def unavailable_model(**kwargs):
        raise RuntimeError("cloud model unavailable")

    request = FileTaskRequest(
        task="将内容总结",
        run_id="readonly_context_fallback",
        selection="客户\t产品\t数量\n杭州新汇鑫光电有限公司\tLASER\t1",
        selection_source="雷鸟访谈问题.docx",
        files=[
            FileTaskFile(
                path="AI Agent.pptx",
                name="AI Agent.pptx",
                type="pptx",
                content="第一页介绍 AI Agent 的目标。第二页说明工具调用和任务执行流程。",
            )
        ],
    )

    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=unavailable_model).run(request))
    run_started = events[0]
    plan_created = next(event for event in events if event.type == "plan.created")
    fallback_message = next(event for event in events if event.payload.get("fallback"))
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert run_started.payload["output_mode"] == "answer"
    assert plan_created.payload["summary"] == "准备处理 1 个文件和 1 段选区。"
    assert not any(event.type == "run.error" for event in events)
    assert fallback_message.payload["tool_name"] == "model_message"
    assert fallback_message.payload["model_unavailable"] is True
    assert check_finished.payload["passed"] is True
    assert check_finished.payload["status"] == "context_summary_fallback"
    assert check_finished.payload["runtime"] == {
        "execution_path": "readonly_fallback",
        "terminal_status": "context_summary_fallback",
        "model_unavailable": True,
        "readonly_fallback_used": True,
        "planner": {
            "backend": "",
            "source": "",
            "policy": "",
            "transport": "",
            "reason": "",
        },
    }
    assert run_finished.payload["completed_task"] is True
    assert run_finished.payload["runtime"] == check_finished.payload["runtime"]
    assert "模型暂不可用" in run_finished.payload["summary"]
    assert "雷鸟访谈问题.docx" in run_finished.payload["summary"]
    assert "AI Agent.pptx" in run_finished.payload["summary"]


def test_file_task_runtime_treats_advisory_analysis_about_modifications_as_hybrid_not_write():
    model_answer = "建议先调整市场进入顺序，再补充竞争壁垒与财务假设。"

    def fake_model(**kwargs):
        return {"content": model_answer, "tool_calls": []}

    request = FileTaskRequest(
        task="分析这个投资建议书，看看有哪些大方向需要修改的地方",
        run_id="advisory_analysis_demo",
        target_path="雷鸟创新-投资建议书.docx",
        files=[
            FileTaskFile(
                path="雷鸟创新-投资建议书.docx",
                name="雷鸟创新-投资建议书.docx",
                type="docx",
                target=True,
                content="业务概览、竞争格局、融资计划。",
            )
        ],
    )

    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model, max_rounds=2).run(request))
    run_started = events[0]
    plan_created = next(event for event in events if event.type == "plan.created")
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert run_started.payload["output_mode"] == "hybrid"
    assert run_started.payload["task_family"] == "analyze"
    assert run_started.payload["operation_kind"] == "read"
    assert run_started.payload["write_intent"] is False
    assert plan_created.payload["steps"][1]["description"] == "模型先读取文件并给出可应用的分析建议；当前轮不默认直接写入原文件。"
    assert check_finished.payload["passed"] is True
    assert check_finished.payload["summary"] == "已完成分析建议，当前未直接写入文件。"
    assert run_finished.payload["summary"] == model_answer
    assert run_finished.payload["completed_task"] is True


def test_file_task_runtime_executes_model_planned_write_and_emits_file_change():
    responses = iter([
        {
            "content": "准备写入 Word。",
            "tool_calls": [
                {
                    "name": "write_docx_content",
                    "args": {"path": "report.docx", "paragraphs": '[{"text":"hello"}]'},
                }
            ],
        },
        {"content": "已完成。", "tool_calls": []},
    ])

    def fake_model(**kwargs):
        return next(responses)

    def fake_executor(tool_name, args):
        if tool_name == "write_docx_content":
            return json.dumps({
                "path": args["path"],
                "operation": tool_name,
                "summary": "已写入 1 个段落到 Word 文档",
                "file_type": "docx",
                "change_type": "modify",
                "focus": True,
            }, ensure_ascii=False)
        if tool_name == "verify_task_completion":
            return json.dumps({"completed": True, "confidence": 0.9, "summary": "写入已核验"}, ensure_ascii=False)
        return ""

    request = FileTaskRequest(task="修改当前文件并保存", run_id="write_demo")
    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model).run(request))

    check_finished = next(event for event in events if event.type == "check.finished")
    file_changed = next(event for event in events if event.type == "file.changed")
    run_finished = events[-1]

    assert file_changed.payload["path"] == "report.docx"
    assert check_finished.payload["passed"] is True
    assert check_finished.payload["status"] == "verified"
    assert run_finished.type == "run.finished"
    assert run_finished.payload["completed_task"] is True


def test_file_task_runtime_passes_structured_file_changes_to_checker():
    responses = iter([
        {
            "content": "准备写入 Word。",
            "tool_calls": [
                {
                    "name": "write_docx_content",
                    "args": {"path": "report.docx", "paragraphs": '[{"text":"hello"}]'},
                }
            ],
        },
        {"content": "已完成。", "tool_calls": []},
    ])
    captured = {}

    def fake_model(**kwargs):
        return next(responses)

    def fake_executor(tool_name, args):
        if tool_name == "write_docx_content":
            return json.dumps({
                "path": args["path"],
                "operation": tool_name,
                "summary": "已写入 1 个段落到 Word 文档",
                "file_type": "docx",
                "change_type": "modify",
                "paragraphs_written": 1,
                "focus": True,
            }, ensure_ascii=False)
        if tool_name == "verify_task_completion":
            captured.update(args)
            return json.dumps({"completed": True, "confidence": 0.9, "summary": "写入已核验"}, ensure_ascii=False)
        return ""

    request = FileTaskRequest(task="修改当前文件并保存", run_id="write_structured_check_demo", target_path="report.docx")
    list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model).run(request))

    assert captured["target_path"] == "report.docx"
    parsed_changes = json.loads(captured["file_changes"])
    assert parsed_changes[0]["path"] == "report.docx"
    assert parsed_changes[0]["operation"] == "write_docx_content"
    assert parsed_changes[0]["paragraphs_written"] == 1


def test_file_task_runtime_ignores_planner_metadata_from_model_response():
    def fake_model(**kwargs):
        request = kwargs["request"]
        assert request.options.get("planner_policy") == "native_only"
        assert not request.options.get("planner_backend")
        return {
            "content": "已总结：alpha beta gamma",
            "tool_calls": [],
            "_planner": {
                "backend": "hermes",
                "source": "external",
                "policy": "prefer_hermes",
                "transport": "embedded",
                "reason": "external_system_task",
                "fallback_from": "native",
            },
        }

    request = FileTaskRequest(
        task="访问网页并整理报告",
        run_id="planner_event_demo",
        options={"planner_backend": "hermes", "planner_policy": "prefer_hermes"},
    )
    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(request))

    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = next(event for event in events if event.type == "run.finished")

    assert not any(event.type == "planner.selected" for event in events)
    assert not any(event.type == "planner.fallback" for event in events)
    assert check_finished.payload["runtime"] == {
        "execution_path": "native",
        "terminal_status": "completed",
        "model_unavailable": False,
        "readonly_fallback_used": False,
        "planner": {
            "backend": "native",
            "source": "native",
            "policy": "native_only",
            "transport": "native",
            "reason": "file_task_native_only",
            "round": 1,
        },
    }
    assert run_finished.payload["runtime"] == check_finished.payload["runtime"]


def test_file_task_runtime_emits_model_confirmed_plan_before_tools():
    responses = iter([
        {
            "content": "我会先读取表格，再把表格写入 Word 并核验结果。",
            "tool_calls": [
                {
                    "name": "read_sheet_data",
                    "args": {"path": "sales.xlsx", "sheet_name": "汇总表", "max_rows": 200},
                },
                {
                    "name": "insert_excel_as_docx_table",
                    "args": {
                        "source_path": "sales.xlsx",
                        "target_path": "report.docx",
                        "sheet_name": "汇总表",
                        "table_title": "销售台账数据",
                    },
                },
            ],
        },
        {"content": "已完成写入。", "tool_calls": []},
    ])

    def fake_model(**kwargs):
        return next(responses)

    def fake_executor(tool_name, args):
        if tool_name == "read_sheet_data":
            return json.dumps({"sheet": "汇总表", "row_count": 200}, ensure_ascii=False)
        if tool_name == "insert_excel_as_docx_table":
            return json.dumps(
                {
                    "path": args["target_path"],
                    "source_path": args["source_path"],
                    "summary": "已将工作表“汇总表”的 200 行数据写入 Word 表格",
                    "file_type": "docx",
                    "change_type": "modify",
                    "sheet": "汇总表",
                    "rows_written": 200,
                    "columns_written": 4,
                },
                ensure_ascii=False,
            )
        if tool_name == "verify_task_completion":
            return json.dumps({"completed": True, "confidence": 0.95, "summary": "写入已核验"}, ensure_ascii=False)
        return ""

    events = list(
        FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model).run(
            FileTaskRequest(
                task="将 xlsx 信息加入 docx",
                run_id="confirmed_plan_demo",
                target_path="report.docx",
                files=[
                    FileTaskFile(path="sales.xlsx", name="销售台账.xlsx", type="xlsx"),
                    FileTaskFile(path="report.docx", name="雷鸟访谈问题.docx", type="docx", target=True),
                ],
            )
        )
    )

    event_types = [event.type for event in events]
    plan_index = event_types.index("plan.confirmed")
    first_tool_index = next(
        idx for idx, event in enumerate(events)
        if event.type == "tool.started" and event.step_id.startswith("tool_")
    )
    confirmed = events[plan_index]

    assert plan_index < first_tool_index
    assert confirmed.step_id == "execute"
    assert confirmed.payload["summary"] == "我会先读取表格，再把表格写入 Word 并核验结果。"
    assert [step["title"] for step in confirmed.payload["steps"]] == [
        "读取 Excel 表格",
        "写入 Word 表格",
        "核验结果",
    ]
    assert "sales.xlsx" in confirmed.payload["steps"][0]["description"]
    assert "report.docx" in confirmed.payload["steps"][1]["description"]


def test_file_task_runtime_accepts_execution_brief_before_tool_calls():
    seen_last_messages = []

    def fake_executor(tool_name, args):
        if tool_name == "write_docx_content":
            return json.dumps(
                {
                    "success": True,
                    "path": args["path"],
                    "file_type": "docx",
                    "operation": "write_docx_content",
                    "summary": "已写入 2 个段落到 Word 文档",
                    "change_type": "modify",
                    "paragraphs_written": 2,
                },
                ensure_ascii=False,
            )
        if tool_name == "verify_task_completion":
            return json.dumps({"completed": True, "summary": "report.docx 已完成更新。"}, ensure_ascii=False)
        raise AssertionError(f"unexpected tool call: {tool_name}")

    def fake_model(**kwargs):
        seen_last_messages.append(str(kwargs["messages"][-1]["content"]))
        if any(
            message.get("role") == "function" and message.get("name") == "write_docx_content"
            for message in kwargs["messages"]
        ):
            return {"content": "已完成写入。", "tool_calls": []}
        if "已收到 execution_brief" in str(kwargs["messages"][-1]["content"]):
            return {
                "content": "现在开始写入文档。",
                "tool_calls": [
                    {
                        "id": "write_after_brief",
                        "name": "write_docx_content",
                        "args": {
                            "path": "report.docx",
                            "paragraphs": '[{"text":"财务预测整理摘要"},{"text":"收入增长主要来自新品放量。"}]',
                        },
                    }
                ],
            }
        return {
            "content": "",
            "execution_brief": {
                "title": "任务分析",
                "summary": "先归纳财务预测结论，再把摘要写入 report.docx。",
                "steps": [
                    {"title": "整理关键结论", "description": "基于显式上下文提炼财务预测的核心结论"},
                    {"title": "写入目标文档", "description": "把整理后的摘要写回 report.docx"},
                ],
                "planned_tools": ["write_docx_content"],
                "write_targets": ["report.docx"],
                "verification": "检查 report.docx 是否真的更新。",
            },
            "tool_calls": [],
        }

    events = list(
        FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model, max_rounds=4).run(
            FileTaskRequest(
                task="整理当前财务预测并写入 report.docx",
                run_id="execution_brief_demo",
                target_path="report.docx",
                files=[FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True)],
            )
        )
    )

    briefed = next(event for event in events if event.type == "plan.briefed")
    confirmed = next(event for event in events if event.type == "plan.confirmed")
    file_changed = next(event for event in events if event.type == "file.changed")
    run_finished = events[-1]

    assert briefed.payload["title"] == "任务分析"
    assert briefed.payload["planned_tools"] == ["write_docx_content"]
    assert confirmed.payload["steps"][0]["tool_name"] == "write_docx_content"
    assert any("已收到 execution_brief" in message for message in seen_last_messages)
    assert file_changed.payload["operation"] == "write_docx_content"
    assert run_finished.payload["completed_task"] is True


def test_file_task_runtime_execution_brief_can_delegate_external_planner():
    class FakeModelClient:
        def __init__(self):
            self.options_seen = []
            self.tool_gap_seen = False

        def call(self, **kwargs):
            request = kwargs["request"]
            messages = kwargs["messages"]
            self.options_seen.append(dict(request.options or {}))

            if any(
                message.get("role") == "function" and message.get("name") == "write_docx_content"
                for message in messages
            ):
                assert request.options.get("planner_policy") == "native_only"
                assert not request.options.get("planner_backend")
                return {
                    "content": "已完成写入。",
                    "tool_calls": [],
                    "_planner": {
                        "backend": "native",
                        "source": "native",
                        "policy": "native_only",
                        "transport": "native",
                        "reason": "file_task_native_only",
                    },
                }

            if "已收到 execution_brief" in str(messages[-1]["content"]):
                assert request.options.get("planner_policy") == "native_only"
                assert not request.options.get("planner_backend")
                return {
                    "content": "继续原生执行写入。",
                    "tool_calls": [
                        {
                            "id": "write_from_hermes",
                            "name": "write_docx_content",
                            "args": {
                                "path": "report.docx",
                                "paragraphs": '[{"text":"Hermes 已接管执行。"}]',
                            },
                        }
                    ],
                    "_planner": {
                        "backend": "native",
                        "source": "native",
                        "policy": "native_only",
                        "transport": "native",
                        "reason": "file_task_native_only",
                    },
                }

            assert request.options.get("planner_policy") == "native_only"
            assert not request.options.get("planner_backend")
            return {
                "content": "",
                "execution_brief": {
                    "title": "任务分析",
                    "summary": "先完成任务分析，再把后续执行委托给 Hermes。",
                    "delegated_planner": "hermes",
                    "steps": [{"title": "委托外部 planner", "description": "让 Hermes 负责后续执行"}],
                },
                "tool_calls": [],
            }

    def fake_executor(tool_name, args):
        if tool_name == "write_docx_content":
            return json.dumps(
                {
                    "success": True,
                    "path": args["path"],
                    "file_type": "docx",
                    "operation": "write_docx_content",
                    "summary": "已写入 1 个段落到 Word 文档",
                    "change_type": "modify",
                    "paragraphs_written": 1,
                },
                ensure_ascii=False,
            )
        if tool_name == "verify_task_completion":
            return json.dumps({"completed": True, "summary": "report.docx 已完成更新。"}, ensure_ascii=False)
        raise AssertionError(f"unexpected tool call: {tool_name}")

    model_client = FakeModelClient()
    events = list(
        FileTaskRuntime(tool_executor=fake_executor, model_client=model_client, max_rounds=4).run(
            FileTaskRequest(
                task="整理当前文档并写入 report.docx",
                run_id="execution_brief_delegate_demo",
                target_path="report.docx",
                files=[FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True)],
            )
        )
    )

    briefed = next(event for event in events if event.type == "plan.briefed")
    run_finished = events[-1]

    assert briefed.payload["delegated_planner"] == "hermes"
    assert all(options.get("planner_policy") == "native_only" for options in model_client.options_seen)
    assert all(not options.get("planner_backend") for options in model_client.options_seen)
    assert not any(event.type == "planner.selected" for event in events)
    assert not any(event.type == "planner.fallback" for event in events)
    assert run_finished.payload["completed_task"] is True


def test_file_task_runtime_classification_defers_planner_without_explicit_override():
    def fake_model(**kwargs):
        return {"content": "已完成摘要。", "tool_calls": []}

    events = list(
        FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model, max_rounds=2).run(
            FileTaskRequest(
                task="总结当前文件内容",
                run_id="planner_deferred_classification_demo",
                files=[FileTaskFile(path="notes.txt", name="notes.txt", type="txt", content="alpha beta", target=True)],
            )
        )
    )

    run_started = events[0]

    assert run_started.payload["planner_policy"] == "native_only"
    assert run_started.payload["planner_backend"] == "native"
    assert run_started.payload["planner_reason"] == "file_task_native_only"
    assert "planner_deferred:model_first" not in run_started.payload["reason_codes"]


def test_file_task_runtime_simple_quick_action_mode_skips_classification_and_plan_created():
    def fake_model(**kwargs):
        return {"content": "已总结当前文件重点。", "tool_calls": []}

    events = list(
        FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model, max_rounds=2).run(
            FileTaskRequest(
                task="请总结当前文件内容",
                run_id="quick_action_simple_demo",
                options={"quick_action_mode": "simple"},
                files=[FileTaskFile(path="notes.txt", name="notes.txt", type="txt", content="alpha beta", target=True)],
            )
        )
    )

    event_types = [event.type for event in events]
    run_started = events[0]
    run_finished = events[-1]

    assert run_started.payload["quick_action_mode"] == "simple"
    assert "task.classified" not in event_types
    assert "plan.created" not in event_types
    assert "plan.checked" in event_types
    plan_checked = next(event for event in events if event.type == "plan.checked")
    assert plan_checked.payload["quick_action_bypass"] is True
    assert plan_checked.payload["passed"] is True
    assert run_finished.payload["completed_task"] is True


def test_file_task_runtime_system_prompt_mentions_execution_brief_protocol():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(task="整理文件并写回目标文档", run_id="execution_brief_prompt_demo")

    system = runtime._build_system_prompt(request, [])

    assert "execution_brief" in system
    assert "首轮协议" in system
    assert "返回 execution_brief 后" in system


def test_file_task_runtime_prompt_guides_answer_mode_without_writeback():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(
        task="总结这个文档",
        files=[FileTaskFile(path="notes.docx", name="notes.docx", type="docx")],
    )

    messages = runtime._build_messages(request, [], request.files)
    system = runtime._build_system_prompt(request, request.files)
    content = messages[-1]["content"]

    assert "当前任务反馈模式：只给答案" in system
    assert "不要调用写入工具" in system
    assert '"task_feedback_mode"' in content
    assert '"output_mode": "answer"' in content
    assert '"should_write_this_round": false' in content


def test_file_task_runtime_prompt_guides_hybrid_mode_as_analysis_first():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(
        task="分析这个投资建议书，看看有哪些大方向需要修改的地方",
        target_path="雷鸟创新-投资建议书.docx",
        files=[FileTaskFile(path="雷鸟创新-投资建议书.docx", name="雷鸟创新-投资建议书.docx", type="docx", target=True)],
    )

    messages = runtime._build_messages(request, [], request.files)
    system = runtime._build_system_prompt(request, request.files)
    content = messages[-1]["content"]

    assert "当前任务反馈模式：先分析后决定" in system
    assert "除非用户这轮已经明确要求直接应用到文件，否则不要直接调用写入工具" in system
    assert '"task_feedback_mode"' in content
    assert '"output_mode": "hybrid"' in content
    assert '"should_write_this_round": false' in content


def test_file_task_runtime_prompt_includes_structured_intent_plan_context():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(
        task="分析这个投资建议书，看看有哪些大方向需要修改的地方",
        target_path="雷鸟创新-投资建议书.docx",
        files=[FileTaskFile(path="雷鸟创新-投资建议书.docx", name="雷鸟创新-投资建议书.docx", type="docx", target=True)],
    )

    messages = runtime._build_messages(request, [], request.files)
    system = runtime._build_system_prompt(request, request.files)
    content = messages[-1]["content"]

    assert "高阶意图规划：" in system
    assert "- 策略：analyze_then_confirm" in system
    assert '"intent_plan"' in content
    assert '"recommended_strategy": "analyze_then_confirm"' in content
    assert '"requires_confirmation": true' in content


def test_file_task_runtime_reuses_execution_context_for_prompt_building():
    class StubIntentPlanner:
        def __init__(self):
            self.calls = 0

        def plan(self, request, files, classification, *, known_tool_gap=None):
            self.calls += 1
            return FileTaskIntentPlan(
                intent_type=classification.task_family,
                goal_statement="先分析，再等待确认。",
                output_mode=classification.output_mode,
                confidence=classification.confidence,
                write_intent=classification.write_intent,
                can_apply=False,
                requires_confirmation=(classification.output_mode == "hybrid"),
                recommended_strategy="analyze_then_confirm",
            )

    class StubModelClient:
        def planner_decision_for_request(self, request):
            class Decision:
                policy = "native_only"
                reason = "covered_by_koto_native"
                preferred_backend = ""

            return Decision()

        def call(self, **kwargs):
            return {"content": "ok", "tool_calls": []}

    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=StubModelClient())
    runtime._intent_planner = StubIntentPlanner()
    request = FileTaskRequest(
        task="分析这个投资建议书，看看有哪些大方向需要修改的地方",
        target_path="雷鸟创新-投资建议书.docx",
        files=[FileTaskFile(path="雷鸟创新-投资建议书.docx", name="雷鸟创新-投资建议书.docx", type="docx", target=True)],
    )

    execution_context = runtime._build_execution_context(request, request.files)
    messages = runtime._build_messages(request, [], request.files, execution_context=execution_context)
    system = runtime._build_system_prompt(request, request.files, execution_context=execution_context)

    assert runtime._intent_planner.calls == 1
    assert execution_context.effective_planner_policy == "native_only"
    assert execution_context.effective_planner_reason == "file_task_native_only"
    assert '"intent_plan"' in messages[-1]["content"]
    assert "高阶意图规划：" in system


def test_file_task_runtime_run_uses_custom_intent_planner_steps_and_payload():
    class StubIntentPlanner:
        def plan(self, request, files, classification, *, known_tool_gap=None):
            return FileTaskIntentPlan(
                intent_type=classification.task_family,
                goal_statement="先分析风险，再等待确认应用。",
                output_mode=classification.output_mode,
                confidence=0.84,
                write_intent=classification.write_intent,
                can_apply=True,
                requires_confirmation=True,
                recommended_strategy="analyze_then_confirm",
                dynamic_steps=[
                    {"id": "context", "title": "收集上下文", "description": "先锁定目标文档与显式输入。"},
                    {"id": "execute", "title": "生成建议", "description": "先做局部分析，再等待确认。"},
                    {"id": "check", "title": "确认出口", "description": "确认当前轮不直接写回。"},
                ],
                reason_codes=["stub_intent_plan"],
            )

    def fake_model(**kwargs):
        return {"content": "已完成分析。", "tool_calls": []}

    runtime = FileTaskRuntime(
        tool_executor=lambda name, args: "",
        model_client=fake_model,
        intent_planner=StubIntentPlanner(),
        max_rounds=1,
    )
    request = FileTaskRequest(
        task="分析这个投资建议书，看看有哪些大方向需要修改的地方",
        run_id="intent_plan_runtime_demo",
        target_path="雷鸟创新-投资建议书.docx",
        files=[FileTaskFile(path="雷鸟创新-投资建议书.docx", name="雷鸟创新-投资建议书.docx", type="docx", target=True)],
    )

    events = list(runtime.run(request))
    run_started = events[0]
    plan_created = next(event for event in events if event.type == "plan.created")

    assert run_started.payload["intent_plan"]["goal_statement"] == "先分析风险，再等待确认应用。"
    assert run_started.payload["intent_plan"]["recommended_strategy"] == "analyze_then_confirm"
    assert plan_created.payload["intent_plan"]["can_apply"] is True
    assert plan_created.payload["steps"][1]["description"] == "先做局部分析，再等待确认。"


def test_file_task_runtime_surfaces_tool_gap_without_retrying_write_guard():
    def fake_model(**kwargs):
        return {
            "content": "当前任务需要新的 Koto 工具。",
            "tool_calls": [],
            "tool_gap": {
                "summary": "当前缺少读取 CAD 文件的 Koto 原生工具。",
                "missing_capability": "read_cad_file",
                "why_missing": "allowlist 中没有可读取 dwg 的工具。",
                "suggested_next_step": "先实现只读 CAD 解析工具，再决定写入方案。",
                "proposed_tool": {
                    "name": "read_cad_file",
                    "description": "解析 DWG/DXF 为可检索的结构化文本。",
                    "parameters": {"type": "object"},
                },
            },
            "_planner": {
                "backend": "hermes",
                "source": "external",
                "policy": "prefer_hermes",
                "transport": "embedded",
                "reason": "unsupported_file_types:dwg",
            },
        }

    request = FileTaskRequest(task="修改 CAD 文件并导出总结", run_id="tool_gap_demo", target_path="drawing.dwg")
    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(request))

    tool_missing = next(event for event in events if event.type == "tool.missing")
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = next(event for event in events if event.type == "run.finished")
    expected_runtime = {
        "execution_path": "native",
        "terminal_status": "tool_gap",
        "model_unavailable": False,
        "readonly_fallback_used": False,
        "planner": {
            "backend": "native",
            "source": "native",
            "policy": "native_only",
            "transport": "native",
            "reason": "file_task_native_only",
            "round": 1,
        },
    }
    expected_artifact = {
        "artifact_type": "koto_next_action_v1",
        "category": "missing_native_tool",
        "tool_design_protocol": "koto_tool_design_v1",
        "tool_design_status": "draft",
        "generated_by": "koto_file_task_runtime",
        "external_planner_required": False,
        "title": "Koto 下一步：read_cad_file",
        "summary": "当前缺少读取 CAD 文件的 Koto 原生工具。",
        "source_task": "修改 CAD 文件并导出总结",
        "target_path": "drawing.dwg",
        "missing_capability": "read_cad_file",
        "why_missing": "allowlist 中没有可读取 dwg 的工具。",
        "suggested_next_step": "先实现只读 CAD 解析工具，再决定写入方案。",
        "implementation_scope": "smallest_next_capability",
        "acceptance_criteria": [
            "为 read_cad_file 提供稳定的 Koto 原生工具入口",
            "工具返回结构需要可被 file-task 规划器直接消费",
            "补齐能力后可重新执行当前任务而无需改写用户意图",
        ],
        "proposed_tool": {
            "name": "read_cad_file",
            "description": "解析 DWG/DXF 为可检索的结构化文本。",
            "parameters": {"type": "object"},
            "returns": "",
            "rationale": "",
        },
        "runtime_context": expected_runtime,
    }

    assert tool_missing.payload == {
        "summary": "当前缺少读取 CAD 文件的 Koto 原生工具。",
        "missing_capability": "read_cad_file",
        "why_missing": "allowlist 中没有可读取 dwg 的工具。",
        "suggested_next_step": "先实现只读 CAD 解析工具，再决定写入方案。",
        "proposed_tool": {
            "name": "read_cad_file",
            "description": "解析 DWG/DXF 为可检索的结构化文本。",
            "parameters": {"type": "object"},
        },
        "next_action_artifact": expected_artifact,
        "runtime": expected_runtime,
        "round": 1,
    }
    assert not any(
        event.type == "tool.finished" and event.payload.get("tool_name") == "write_guard"
        for event in events
    )
    assert check_finished.payload["status"] == "tool_gap"
    assert check_finished.payload["passed"] is False
    assert check_finished.payload["tool_gap"]["missing_capability"] == "read_cad_file"
    assert check_finished.payload["next_action_artifact"] == expected_artifact
    assert check_finished.payload["runtime"] == {
        **expected_runtime,
        "terminal_status": "tool_gap",
    }
    assert run_finished.payload["completed_task"] is False
    assert run_finished.payload["tool_gap"]["missing_capability"] == "read_cad_file"
    assert run_finished.payload["next_action_artifact"] == expected_artifact
    assert run_finished.payload["runtime"] == check_finished.payload["runtime"]


def test_file_task_runtime_does_not_external_fallback_after_tool_gap():
    class FakeModelClient:
        def __init__(self):
            self.options_seen = []
            self.tool_gap_seen = False

        def fallback_planner_backend_for_request(self, request):
            return "hermes"

        def call(self, **kwargs):
            request = kwargs["request"]
            messages = kwargs["messages"]
            self.options_seen.append(dict(request.options or {}))

            if request.options.get("planner_backend") == "hermes":
                self.tool_gap_seen = any(
                    isinstance(message.get("tool_gap"), dict)
                    for message in messages
                    if isinstance(message, dict)
                )
                return {
                    "content": "Hermes 已接管并完成分析。",
                    "tool_calls": [],
                    "_planner": {
                        "backend": "hermes",
                        "source": "external",
                        "policy": "explicit_backend",
                        "transport": "embedded",
                        "reason": str(request.options.get("planner_runtime_reason") or ""),
                    },
                }

            assert request.options.get("planner_policy") == "native_only"
            assert not request.options.get("planner_backend")
            return {
                "content": "当前缺少 Koto 原生 CAD 工具。",
                "tool_calls": [],
                "tool_gap": {
                    "summary": "当前缺少读取 CAD 文件的 Koto 原生工具。",
                    "missing_capability": "read_cad_file",
                    "why_missing": "allowlist 中没有可读取 dwg 的工具。",
                    "suggested_next_step": "先实现只读 CAD 解析工具，再决定写入方案。",
                },
                "_planner": {
                    "backend": "native",
                    "source": "native",
                    "policy": "native_only",
                    "transport": "native",
                    "reason": "native_tool_design_required:read_cad_file",
                },
            }

    model_client = FakeModelClient()
    events = list(
        FileTaskRuntime(tool_executor=lambda name, args: "", model_client=model_client, max_rounds=4).run(
            FileTaskRequest(
                task="分析 CAD 文件并整理结论",
                run_id="tool_gap_external_fallback_demo",
                target_path="drawing.dwg",
            )
        )
    )

    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = next(event for event in events if event.type == "run.finished")

    assert model_client.options_seen[0].get("planner_policy") == "native_only"
    assert len(model_client.options_seen) == 1
    assert not any(event.type == "planner.selected" for event in events)
    assert not any(event.type == "planner.fallback" for event in events)
    assert model_client.tool_gap_seen is False
    assert check_finished.payload["status"] == "tool_gap"
    assert check_finished.payload["passed"] is False
    assert run_finished.payload["completed_task"] is False
    assert run_finished.payload["runtime"]["execution_path"] == "native"


def test_file_task_runtime_does_not_external_fallback_after_native_model_failure():
    class FakeModelClient:
        def __init__(self):
            self.options_seen = []

        def fallback_planner_backend_for_request(self, request):
            return "hermes"

        def call(self, **kwargs):
            request = kwargs["request"]
            self.options_seen.append(dict(request.options or {}))

            if request.options.get("planner_backend") == "hermes":
                return {
                    "content": "Hermes 已生成最终摘要。",
                    "tool_calls": [],
                    "_planner": {
                        "backend": "hermes",
                        "source": "external",
                        "policy": "explicit_backend",
                        "transport": "embedded",
                        "reason": str(request.options.get("planner_runtime_reason") or ""),
                    },
                }

            raise RuntimeError("native provider offline")

    model_client = FakeModelClient()
    events = list(
        FileTaskRuntime(tool_executor=lambda name, args: "", model_client=model_client, max_rounds=3).run(
            FileTaskRequest(
                task="总结当前文件内容",
                run_id="native_model_failure_external_fallback_demo",
                files=[FileTaskFile(path="notes.txt", name="notes.txt", type="txt", content="alpha beta", target=True)],
            )
        )
    )

    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = next(event for event in events if event.type == "run.finished")

    assert model_client.options_seen[0]["planner_policy"] == "native_only"
    assert len(model_client.options_seen) == 1
    assert not any(event.type == "planner.selected" for event in events)
    assert not any(event.type == "planner.fallback" for event in events)
    assert check_finished.payload["status"] == "context_summary_fallback"
    assert check_finished.payload["passed"] is True
    assert run_finished.payload["completed_task"] is True
    assert run_finished.payload["runtime"]["execution_path"] == "readonly_fallback"
    assert "Hermes" not in str(run_finished.payload["summary"])


def test_file_task_runtime_does_not_external_fallback_after_verify_error():
    class FakeModelClient:
        def __init__(self):
            self.options_seen = []

        def fallback_planner_backend_for_request(self, request):
            return "hermes"

        def call(self, **kwargs):
            request = kwargs["request"]
            messages = kwargs["messages"]
            self.options_seen.append(dict(request.options or {}))

            if request.options.get("planner_backend") == "hermes":
                if any(
                    message.get("role") == "function" and message.get("name") == "write_docx_content"
                    for message in messages
                ):
                    return {
                        "content": "已完成修复。",
                        "tool_calls": [],
                        "_planner": {
                            "backend": "hermes",
                            "source": "external",
                            "policy": "explicit_backend",
                            "transport": "embedded",
                            "reason": str(request.options.get("planner_runtime_reason") or ""),
                        },
                    }
                return {
                    "content": "Hermes 开始修复写入。",
                    "tool_calls": [
                        {
                            "id": "hermes_write_docx",
                            "name": "write_docx_content",
                            "args": {
                                "path": "report.docx",
                                "paragraphs": '[{"text":"Hermes 修正后的内容。"}]',
                            },
                        }
                    ],
                    "_planner": {
                        "backend": "hermes",
                        "source": "external",
                        "policy": "explicit_backend",
                        "transport": "embedded",
                        "reason": str(request.options.get("planner_runtime_reason") or ""),
                    },
                }

            if any(
                message.get("role") == "function" and message.get("name") == "write_docx_content"
                for message in messages
            ):
                return {
                    "content": "原生写入完成。",
                    "tool_calls": [],
                    "_planner": {
                        "backend": "native",
                        "source": "native",
                        "policy": "native_only",
                        "transport": "native",
                        "reason": "covered_by_koto_native",
                    },
                }

            return {
                "content": "先写入 report.docx。",
                "tool_calls": [
                    {
                        "id": "native_write_docx",
                        "name": "write_docx_content",
                        "args": {
                            "path": "report.docx",
                            "paragraphs": '[{"text":"原生初稿。"}]',
                        },
                    }
                ],
                "_planner": {
                    "backend": "native",
                    "source": "native",
                    "policy": "native_only",
                    "transport": "native",
                    "reason": "covered_by_koto_native",
                },
            }

    verify_calls = {"count": 0}

    def fake_executor(tool_name, args):
        if tool_name == "write_docx_content":
            return json.dumps(
                {
                    "success": True,
                    "path": args["path"],
                    "file_type": "docx",
                    "operation": "write_docx_content",
                    "summary": "已写入 1 个段落到 Word 文档",
                    "change_type": "modify",
                    "paragraphs_written": 1,
                },
                ensure_ascii=False,
            )
        if tool_name == "verify_task_completion":
            verify_calls["count"] += 1
            if verify_calls["count"] == 1:
                return json.dumps({"error": "judge unavailable"}, ensure_ascii=False)
            return json.dumps({"completed": True, "summary": "report.docx 已完成更新。"}, ensure_ascii=False)
        raise AssertionError(f"unexpected tool call: {tool_name}")

    model_client = FakeModelClient()
    events = list(
        FileTaskRuntime(tool_executor=fake_executor, model_client=model_client, max_rounds=5).run(
            FileTaskRequest(
                task="整理当前文档并写入 report.docx",
                run_id="verify_error_external_fallback_demo",
                target_path="report.docx",
                files=[FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True)],
            )
        )
    )

    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = next(event for event in events if event.type == "run.finished")

    assert model_client.options_seen[0].get("planner_policy") == "native_only"
    assert all(not options.get("planner_backend") for options in model_client.options_seen)
    assert not any(event.type == "planner.selected" for event in events)
    assert not any(event.type == "planner.fallback" for event in events)
    assert verify_calls["count"] == 1
    assert check_finished.payload["status"] == "verify_error"
    assert check_finished.payload["passed"] is False
    assert run_finished.payload["completed_task"] is False


def test_file_task_runtime_pptx_design_retry_points_to_native_tool():
    def fake_model(**kwargs):
        return {
            "content": "很抱歉，我无法直接为 PPTX 文件设计主题和排版。",
            "tool_calls": [],
            "_planner": {
                "backend": "native",
                "source": "native",
                "policy": "native_only",
                "reason": "covered_by_koto_native",
            },
        }

    request = FileTaskRequest(
        task="目前这个 pptx 是没有风格设计的，请帮我设计主题和排版",
        run_id="pptx_design_native_retry",
        files=[FileTaskFile(path="deck.pptx", name="deck.pptx", type="pptx", content="PPT 文本上下文", target=True)],
        target_path="deck.pptx",
    )
    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(request))

    write_guard = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "write_guard"
    )
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = next(event for event in events if event.type == "run.finished")

    assert not any(event.type == "tool.missing" for event in events)
    assert "design_pptx_theme_layout" in write_guard.payload["result_preview"]
    assert check_finished.payload["status"] == "no_file_change"
    assert check_finished.payload["passed"] is False
    assert run_finished.payload["completed_task"] is False


def test_file_task_runtime_parses_native_tool_design_protocol_from_model_text():
    model_payload = {
        "tool_gap": {
            "summary": "需要一个 CAD 读取工具。",
            "missing_capability": "read_cad_file",
            "why_missing": "现有工具不能解析 DWG/DXF 文件。",
            "suggested_next_step": "生成并实现 Koto 原生 CAD 读取工具。",
            "proposed_tool": {
                "name": "read_cad_file",
                "description": "解析 DWG/DXF 为可检索的结构化文本。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_entities": {"type": "integer"},
                    },
                    "required": ["path"],
                },
                "returns": "结构化 CAD 文本摘要。",
                "rationale": "CAD 文件需要格式感知解析。",
                "implementation_notes": ["第一版只读，不写回 CAD。"],
                "safety_constraints": ["不得修改源文件。"],
                "acceptance_tests": ["DWG/DXF 示例文件可以返回图层和实体摘要。"],
            },
        }
    }

    def fake_model(**kwargs):
        assert "koto_tool_design_v1" in kwargs["system"]
        assert "优先组合多个现有工具" in kwargs["system"]
        assert "tool_design_protocol" in kwargs["messages"][-1]["content"]
        return {
            "content": json.dumps(model_payload, ensure_ascii=False),
            "tool_calls": [],
            "_planner": {
                "backend": "native",
                "source": "native",
                "policy": "native_only",
                "reason": "covered_by_koto_native",
            },
        }

    request = FileTaskRequest(
        task="分析这个 CAD 文件",
        run_id="native_tool_design_protocol",
        files=[FileTaskFile(path="drawing.dwg", name="drawing.dwg", type="dwg", content="CAD 文件上下文", target=True)],
        target_path="drawing.dwg",
    )
    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(request))

    tool_missing = next(event for event in events if event.type == "tool.missing")
    artifact = tool_missing.payload["next_action_artifact"]

    assert tool_missing.payload["missing_capability"] == "read_cad_file"
    assert tool_missing.payload["proposed_tool"]["implementation_notes"] == ["第一版只读，不写回 CAD。"]
    assert artifact["tool_design_protocol"] == "koto_tool_design_v1"
    assert artifact["external_planner_required"] is False
    assert "DWG/DXF 示例文件可以返回图层和实体摘要。" in artifact["acceptance_criteria"]
    assert events[-1].payload["completed_task"] is False


def test_file_task_runtime_messages_include_capability_profiles():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(
        task="把表格总结写进文档",
        run_id="capability_context_demo",
        current_file=FileTaskFile(path="metrics.xlsx", name="metrics.xlsx", type="xlsx"),
        target_path="summary.docx",
    )

    messages = runtime._build_messages(request, [], [request.current_file])
    content = messages[-1]["content"]

    assert "file_capability_profiles" in content
    assert '"format": "xlsx"' in content
    assert '"format": "docx"' in content
    assert '"write_support": "native"' in content


def test_file_task_runtime_followup_feedback_messages_are_not_framed_as_new_task():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(
        task="为什么这次结果不好？",
        run_id="followup_feedback_demo",
        current_file=FileTaskFile(path="translation.docx", name="translation.docx", type="docx"),
        target_path="translation.docx",
        history=[
            {"role": "user", "content": "根据原文审校这个译稿"},
            {"role": "assistant", "content": "已生成第一版审校结果"},
        ],
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "question",
                "user_feedback": "为什么这次结果不好？",
                "previous_run_id": "run_prev_001",
                "previous_task_summary": "已生成第一版审校结果",
                "previous_user_request": "根据原文审校这个译稿",
                "previous_task_request": "根据原文审校这个译稿",
                "previous_task_mode": "doc_annotate_bridge",
                "previous_completed_task": "true",
            }
        },
    )

    messages = runtime._build_messages(request, [], [request.current_file])
    system = runtime._build_system_prompt(request, [request.current_file])
    content = messages[-1]["content"]

    assert "用户正在对上一轮文件任务结果提出反馈" in content
    assert '"followup_context"' in content
    assert '"previous_run_id": "run_prev_001"' in content
    assert '"followup_action": "question"' in content
    assert '"previous_task_summary": "已生成第一版审校结果"' in content
    assert "不要把这条消息当成新的文件执行任务" in content
    assert "不要默认把它当作全新的执行任务" in system
    assert "不要调用写入工具" in system


def test_file_task_runtime_followup_improve_is_framed_as_same_task_iteration():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(
        task="请继续优化上一轮任务结果",
        run_id="followup_improve_demo",
        target_path="report.docx",
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "improve",
                "user_feedback": "请继续优化上一轮任务结果",
                "previous_run_id": "run_prev_002",
                "previous_task_summary": "已写入初稿结论",
                "previous_task_request": "把结论写进 report.docx",
                "previous_task_mode": "whitebox_v1",
                "previous_task_family": "transform",
                "previous_task_operation_kind": "write",
                "previous_task_execution_mode": "generic_tool_loop",
                "previous_completed_task": "true",
            }
        },
    )

    messages = runtime._build_messages(request, [], [])
    system = runtime._build_system_prompt(request, [])
    content = messages[-1]["content"]

    assert "用户要求在上一轮文件任务结果基础上继续优化" in content
    assert '"followup_action": "improve"' in content
    assert '"previous_task_request": "把结论写进 report.docx"' in content
    assert '"previous_task_family": "transform"' in content
    assert '"previous_task_execution_mode": "generic_tool_loop"' in content
    assert "同一任务的后续处理回合" in content
    assert "同一任务的后续回合" in system
    assert "可以继续调用工具修正目标文件" in system


def test_file_task_runtime_followup_apply_is_framed_as_same_task_writeback():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(
        task="请把上一轮已经给出的建议直接应用到目标文件",
        run_id="followup_apply_demo",
        target_path="report.docx",
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "apply",
                "user_feedback": "请把上一轮已经给出的建议直接应用到目标文件",
                "previous_run_id": "run_prev_003",
                "previous_task_summary": "已给出结构调整和措辞修改建议",
                "previous_task_request": "分析这份建议书，看看有哪些地方需要修改",
                "previous_task_mode": "whitebox_v1",
                "previous_task_family": "analyze",
                "previous_task_execution_mode": "generic_tool_loop",
                "previous_task_output_mode": "hybrid",
                "previous_task_intent_can_apply": "true",
                "previous_task_intent_requires_confirmation": "true",
                "previous_completed_task": "true",
            }
        },
    )

    messages = runtime._build_messages(request, [], [])
    system = runtime._build_system_prompt(request, [])
    content = messages[-1]["content"]

    assert "用户要求把上一轮文件任务中已经给出的建议直接应用到目标文件" in content
    assert '"followup_action": "apply"' in content
    assert '"previous_task_output_mode": "hybrid"' in content
    assert '"previous_task_intent_can_apply": "true"' in content
    assert "同一任务的写回续跑" in system
    assert "这一轮应进入真实写回路径并产生 file.changed" in system


def test_file_task_runtime_classifies_followup_apply_from_previous_hybrid_as_write():
    def fake_model(**kwargs):
        return {"content": "开始应用上一轮建议", "tool_calls": []}

    request = FileTaskRequest(
        task="请直接应用上一轮建议",
        run_id="followup_apply_classification_demo",
        current_file=FileTaskFile(path="report.docx", name="report.docx", type="docx", content="现有内容"),
        target_path="report.docx",
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "apply",
                "user_feedback": "请直接应用上一轮建议",
                "previous_task_mode": "whitebox_v1",
                "previous_task_family": "analyze",
                "previous_task_execution_mode": "generic_tool_loop",
                "previous_task_output_mode": "hybrid",
                "previous_task_intent_can_apply": "true",
                "previous_completed_task": "true",
            }
        },
    )

    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(request))
    run_started = events[0]

    assert run_started.payload["request_kind"] == "followup"
    assert run_started.payload["output_mode"] == "write"
    assert run_started.payload["task_family"] == "transform"
    assert run_started.payload["operation_kind"] == "write"
    assert run_started.payload["write_intent"] is True
    assert "followup_action:apply" in run_started.payload["reason_codes"]
    assert "followup_apply_write_intent" in run_started.payload["reason_codes"]


def test_file_task_runtime_diagnostic_question_with_write_words_stays_answer_only():
    request = FileTaskRequest(
        task="为什么这个任务会失败删除这里面所有修改批注",
        run_id="diagnostic_question_write_word_demo",
        current_file=FileTaskFile(path="translation.docx", name="translation.docx", type="docx", content="现有内容"),
        target_path="translation.docx",
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "question",
                "user_feedback": "为什么这个任务会失败删除这里面所有修改批注",
                "previous_task_mode": "doc_annotate_bridge",
                "previous_task_family": "annotate",
                "previous_task_execution_mode": "annotate_tool_loop",
                "previous_task_output_mode": "write",
                "previous_completed_task": "true",
            }
        },
    )

    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {"content": "先解释失败原因。", "tool_calls": []}).run(request))
    run_started = events[0]

    assert run_started.payload["request_kind"] == "followup"
    assert run_started.payload["output_mode"] == "answer"
    assert run_started.payload["task_family"] == "analyze"
    assert run_started.payload["operation_kind"] == "read"
    assert run_started.payload["write_intent"] is False
    assert run_started.payload["docx_annotation_request"] is False
    assert "followup_action:question" in run_started.payload["reason_codes"]
    assert "diagnostic_request" in run_started.payload["reason_codes"]
    assert "diagnostic_overrode_write_intent" in run_started.payload["reason_codes"]
    assert run_started.payload["intent_plan"]["recommended_strategy"] == "diagnose_then_answer"


def test_file_task_runtime_followup_improve_carries_previous_file_changes_and_no_repeat_insert_guidance():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(
        task="请继续优化上一轮任务结果",
        run_id="followup_improve_insert_guard_demo",
        target_path="report.docx",
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "improve",
                "user_feedback": "请继续优化上一轮任务结果",
                "previous_task_summary": "已将工作表“P&L”的 50 行数据写入 Word 表格",
                "previous_task_request": "整理 xlsx 中的财务预测，并加入 docx",
                "previous_completed_task": "true",
                "previous_task_file_changes": [
                    {
                        "path": "report.docx",
                        "operation": "insert_excel_as_docx_table",
                        "sheet": "P&L",
                        "rows_written": 50,
                        "columns_written": 13,
                        "table_title": "利润表 (P&L)",
                    }
                ],
            }
        },
    )

    messages = runtime._build_messages(request, [], [])
    system = runtime._build_system_prompt(request, [])
    content = messages[-1]["content"]

    assert '"previous_task_file_changes": [' in content
    assert '"operation": "insert_excel_as_docx_table"' in content
    assert "不要重复同一插表" in content
    assert "不要再次插入同一张表" in system


def test_file_task_runtime_classifies_followup_improve_from_previous_annotation_metadata():
    def fake_model(**kwargs):
        return {"content": "继续优化上一轮批注结果", "tool_calls": []}

    request = FileTaskRequest(
        task="请继续优化上一轮结果",
        run_id="followup_classification_demo",
        current_file=FileTaskFile(path="translation.docx", name="translation.docx", type="docx", content="现有译稿"),
        target_path="translation.docx",
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "improve",
                "user_feedback": "请继续优化上一轮结果",
                "previous_task_mode": "whitebox_v1",
                "previous_task_family": "annotate",
                "previous_task_execution_mode": "annotate_tool_loop",
                "previous_completed_task": "true",
            }
        },
    )

    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(request))
    run_started = events[0]

    assert run_started.payload["request_kind"] == "followup"
    assert run_started.payload["task_family"] == "annotate"
    assert run_started.payload["operation_kind"] == "annotate"
    assert run_started.payload["docx_annotation_request"] is True
    assert "followup_previous_task_family:annotate" in run_started.payload["reason_codes"]
    assert "followup_previous_execution_mode:annotate_tool_loop" in run_started.payload["reason_codes"]


def test_file_task_runtime_xlsx_to_docx_write_loop_handles_sheet1_and_string_rows(tmp_path):
    import openpyxl
    from docx import Document

    workbook_path = tmp_path / "sales.xlsx"
    target_path = tmp_path / "target.docx"

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "汇总表"
    sheet.append(["客户名称", "产品名称", "数量"])
    sheet.append(["杭州新汇鑫光电有限公司", "LASER", 1])
    sheet.append(["山东镭鸟激光设备有限公司", "LASER", 2])
    workbook.save(workbook_path)

    document = Document()
    document.add_paragraph("雷鸟访谈问题")
    document.save(target_path)

    responses = iter([
        {
            "content": "先读取 Excel。",
            "tool_calls": [
                {
                    "name": "read_sheet_data",
                    "args": {"path": str(workbook_path), "sheet_name": "Sheet1", "max_rows": "2"},
                }
            ],
        },
        {
            "content": "把 Excel 表格加入 Word。",
            "tool_calls": [
                {
                    "name": "insert_excel_as_docx_table",
                    "args": {
                        "source_path": str(workbook_path),
                        "target_path": str(target_path),
                        "sheet_name": "Sheet1",
                        "table_title": "销售台账数据",
                        "max_rows": "2",
                    },
                }
            ],
        },
        {"content": "已将销售台账数据加入 Word。", "tool_calls": []},
    ])

    def fake_model(**kwargs):
        return next(responses)

    request = FileTaskRequest(
        task="把 xlsx 表格加入 docx",
        run_id="xlsx_docx_loop",
        model_mode="local",
        target_path=str(target_path),
        files=[
            FileTaskFile(path=str(workbook_path), name="销售台账.xlsx", type="xlsx", content="销售台账 Excel"),
            FileTaskFile(path=str(target_path), name="雷鸟访谈问题.docx", type="docx", content="目标 Word 文档", target=True),
        ],
    )

    events = list(FileTaskRuntime(model_client=fake_model).run(request))
    read_finished = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "read_sheet_data"
    )
    insert_finished = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "insert_excel_as_docx_table"
    )
    file_changed = next(event for event in events if event.type == "file.changed")
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert read_finished.payload["success"] is True
    assert "汇总表" in read_finished.payload["result_preview"]
    assert "Sheet1" in read_finished.payload["result_preview"]
    assert insert_finished.payload["success"] is True
    assert "汇总表" in insert_finished.payload["result_preview"]
    assert file_changed.payload["path"] == str(target_path)
    assert file_changed.payload["sheet"] == "汇总表"
    assert file_changed.payload["requested_sheet"] == "Sheet1"
    assert file_changed.payload["rows_written"] == 2
    assert file_changed.payload["columns_written"] == 3
    assert check_finished.payload["passed"] is True
    assert check_finished.payload["status"] == "verified"
    assert run_finished.payload["completed_task"] is True

    saved = Document(str(target_path))
    assert len(saved.tables) == 1
    assert saved.tables[0].cell(1, 0).text == "杭州新汇鑫光电有限公司"
    assert saved.tables[0].cell(2, 0).text == "山东镭鸟激光设备有限公司"


def test_file_task_runtime_xlsx_to_docx_write_loop_fails_without_file_change(tmp_path):
    from docx import Document

    target_path = tmp_path / "target.docx"
    document = Document()
    document.add_paragraph("雷鸟访谈问题")
    document.save(target_path)

    responses = iter([
        {
            "content": "尝试把 Excel 表格加入 Word。",
            "tool_calls": [
                {
                    "name": "insert_excel_as_docx_table",
                    "args": {
                        "source_path": str(tmp_path / "missing.xlsx"),
                        "target_path": str(target_path),
                        "sheet_name": "Sheet1",
                        "max_rows": "50",
                    },
                }
            ],
        },
        {"content": "已完成。", "tool_calls": []},
    ])

    def fake_model(**kwargs):
        return next(responses)

    request = FileTaskRequest(
        task="把 xlsx 表格加入 docx",
        run_id="xlsx_docx_no_change",
        target_path=str(target_path),
        files=[FileTaskFile(path=str(target_path), name="雷鸟访谈问题.docx", type="docx", content="目标 Word 文档", target=True)],
    )

    events = list(FileTaskRuntime(model_client=fake_model).run(request))
    insert_finished = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "insert_excel_as_docx_table"
    )
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert insert_finished.payload["success"] is False
    assert "File not found" in insert_finished.payload["result_preview"]
    assert not any(event.type == "file.changed" for event in events)
    assert check_finished.payload["passed"] is False
    assert check_finished.payload["status"] == "no_file_change"
    assert run_finished.payload["completed_task"] is False
    assert len(Document(str(target_path)).tables) == 0


def test_file_task_runtime_retries_write_task_after_read_only_model_answer(tmp_path):
    import openpyxl
    from docx import Document

    workbook_path = tmp_path / "sales.xlsx"
    target_path = tmp_path / "target.docx"

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "汇总表"
    sheet.append(["客户名称", "产品名称", "数量"])
    sheet.append(["杭州新汇鑫光电有限公司", "LASER", 1])
    sheet.append(["山东镭鸟激光设备有限公司", "LASER", 2])
    workbook.save(workbook_path)

    document = Document()
    document.add_paragraph("雷鸟访谈问题")
    document.save(target_path)

    responses = iter([
        {
            "content": "先读取 Excel。",
            "tool_calls": [
                {
                    "name": "read_sheet_data",
                    "args": {"path": str(workbook_path), "sheet_name": "Sheet1", "max_rows": "2"},
                }
            ],
        },
        {"content": "我已经读取完表格内容。", "tool_calls": []},
        {
            "content": "现在写入 Word。",
            "tool_calls": [
                {
                    "name": "insert_excel_as_docx_table",
                    "args": {
                        "source_path": str(workbook_path),
                        "target_path": str(target_path),
                        "sheet_name": "汇总表",
                        "table_title": "销售台账数据",
                        "max_rows": "2",
                    },
                }
            ],
        },
        {"content": "已将销售台账数据加入 Word。", "tool_calls": []},
    ])
    seen_last_messages = []

    def fake_model(**kwargs):
        seen_last_messages.append(kwargs["messages"][-1]["content"])
        return next(responses)

    request = FileTaskRequest(
        task="把 xlsx 表格加入 docx",
        run_id="xlsx_docx_retry_after_read_only",
        model_mode="local",
        target_path=str(target_path),
        files=[
            FileTaskFile(path=str(workbook_path), name="销售台账.xlsx", type="xlsx", content="销售台账 Excel"),
            FileTaskFile(path=str(target_path), name="雷鸟访谈问题.docx", type="docx", content="目标 Word 文档", target=True),
        ],
    )

    events = list(FileTaskRuntime(model_client=fake_model, max_rounds=4).run(request))
    write_guard = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "write_guard"
    )
    insert_finished = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "insert_excel_as_docx_table"
    )
    file_changed = next(event for event in events if event.type == "file.changed")
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert "insert_excel_as_docx_table" in write_guard.payload["result_preview"]
    assert any("insert_excel_as_docx_table" in message for message in seen_last_messages)
    assert insert_finished.payload["success"] is True
    assert file_changed.payload["sheet"] == "汇总表"
    assert check_finished.payload["status"] == "verified"
    assert run_finished.payload["completed_task"] is True
    assert len(Document(str(target_path)).tables) == 1


def test_file_task_runtime_repairs_after_failed_verification(tmp_path):
    target_path = tmp_path / "report.docx"
    target_path.write_text("placeholder", encoding="utf-8")

    responses = iter([
        {
            "content": "先写入第一版。",
            "tool_calls": [
                {
                    "name": "write_docx_content",
                    "args": {"path": str(target_path), "paragraphs": '[{"text":"draft"}]'},
                }
            ],
        },
        {"content": "已完成初稿。", "tool_calls": []},
        {
            "content": "根据核验结果修复文档。",
            "tool_calls": [
                {
                    "name": "write_docx_content",
                    "args": {"path": str(target_path), "paragraphs": '[{"text":"final"}]'},
                }
            ],
        },
        {"content": "修复完成。", "tool_calls": []},
    ])
    seen_last_messages = []
    verify_calls = []
    write_calls = []

    def fake_model(**kwargs):
        seen_last_messages.append(kwargs["messages"][-1]["content"])
        return next(responses)

    def fake_executor(tool_name, args):
        if tool_name == "write_docx_content":
            write_calls.append(dict(args))
            return json.dumps({
                "path": args["path"],
                "operation": tool_name,
                "summary": "已写入 Word 文档",
                "file_type": "docx",
                "change_type": "modify",
                "focus": True,
            }, ensure_ascii=False)
        if tool_name == "verify_task_completion":
            verify_calls.append(dict(args))
            if len(verify_calls) == 1:
                return json.dumps({
                    "completed": False,
                    "summary": "正文还没有写到目标位置。",
                    "remaining_steps": ["把正文结论写到目标段落，而不是停留在草稿区"],
                }, ensure_ascii=False)
            return json.dumps({
                "completed": True,
                "summary": "修复后核验通过。",
                "confidence": 0.93,
            }, ensure_ascii=False)
        raise AssertionError(f"unexpected tool call: {tool_name}")

    request = FileTaskRequest(
        task="修改当前文件并保存",
        run_id="repair_after_verify_demo",
        target_path=str(target_path),
        files=[FileTaskFile(path=str(target_path), name="report.docx", type="docx", content="现有 Word 文档", target=True)],
    )

    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model, max_rounds=4).run(request))

    repair_guard = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "repair_guard"
    )
    check_finished_events = [event for event in events if event.type == "check.finished"]
    run_finished = events[-1]

    assert len(write_calls) == 2
    assert len(verify_calls) == 2
    assert len(check_finished_events) == 2
    assert check_finished_events[0].payload["status"] == "needs_attention"
    assert check_finished_events[1].payload["status"] == "verified"
    assert "核验未通过" in repair_guard.payload["result_preview"]
    assert any("正文还没有写到目标位置" in message for message in seen_last_messages)
    assert any("把正文结论写到目标段落" in message for message in seen_last_messages)
    assert run_finished.payload["completed_task"] is True
    assert run_finished.payload["summary"] == "修复后核验通过。"


def test_file_task_runtime_preserves_write_blocked_status_in_immediate_verify(tmp_path):
    target_path = tmp_path / "locked.docx"
    target_path.write_text("placeholder", encoding="utf-8")

    responses = iter([
        {
            "content": "尝试写入目标文档。",
            "tool_calls": [
                {
                    "name": "write_docx_content",
                    "args": {"path": str(target_path), "paragraphs": '[{"text":"draft"}]'},
                }
            ],
        },
        {"content": "写入受阻，停止继续。", "tool_calls": []},
    ])

    def fake_model(**kwargs):
        return next(responses)

    def fake_executor(tool_name, args):
        if tool_name == "write_docx_content":
            return json.dumps({
                "success": False,
                "status": "write_blocked",
                "path": args["path"],
                "operation": tool_name,
                "summary": "目标文件当前不可写。",
                "suggested_next_step": "关闭占用目标文件的程序或页签后重试。",
                "file_type": "docx",
            }, ensure_ascii=False)
        raise AssertionError(f"unexpected tool call: {tool_name}")

    request = FileTaskRequest(
        task="修改当前文件并保存",
        run_id="write_blocked_immediate_verify_demo",
        target_path=str(target_path),
        files=[FileTaskFile(path=str(target_path), name="locked.docx", type="docx", content="现有 Word 文档", target=True)],
    )

    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model, max_rounds=2).run(request))

    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert check_finished.payload["status"] == "write_blocked"
    assert check_finished.payload["passed"] is False
    assert check_finished.payload["remaining"] == ["关闭占用目标文件的程序或页签后重试。"]
    assert run_finished.payload["completed_task"] is False
    assert run_finished.payload["runtime"]["terminal_status"] == "write_blocked"


def test_file_task_runtime_packages_failed_python_feedback_for_next_model_turn():
    responses = iter([
        {
            "content": "先运行 Python 脚本。",
            "tool_calls": [
                {"name": "run_python_code", "args": {"code": "print(missing_name)"}},
            ],
        },
        {"content": "收到错误后停止重复执行。", "tool_calls": []},
    ])
    seen_last_messages = []

    def fake_model(**kwargs):
        seen_last_messages.append(kwargs["messages"][-1]["content"])
        return next(responses)

    def fake_executor(tool_name, args):
        assert tool_name == "run_python_code"
        return {
            "summary": "Python 脚本执行失败。",
            "stdout": "",
            "stderr": "NameError: name 'missing_name' is not defined",
            "error": "NameError",
            "files": {},
            "_koto_created": [],
            "_koto_modified": [],
        }

    request = FileTaskRequest(task="用 Python 分析当前数据", run_id="python_failure_feedback_demo")
    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model, max_rounds=2).run(request))

    failed_python = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "run_python_code"
    )
    feedback_payload = json.loads(seen_last_messages[1])

    assert failed_python.payload["success"] is False
    assert feedback_payload["tool_name"] == "run_python_code"
    assert feedback_payload["tool_args"] == {"code": "print(missing_name)"}
    assert feedback_payload["success"] is False
    assert feedback_payload["failure_reason"] == "execution_failed"
    assert feedback_payload["retry_same_call_allowed"] is False
    assert feedback_payload["result"]["error"] == "NameError"
    assert feedback_payload["result"]["stderr"] == "NameError: name 'missing_name' is not defined"
    assert "不要重复完全相同的调用" in feedback_payload["next_action"]


def test_file_task_runtime_allows_multiple_python_reads_without_file_markers():
    responses = iter([
        {
            "content": "先读取 Excel。",
            "tool_calls": [
                {"name": "run_python_code", "args": {"code": "print('first read')"}},
            ],
        },
        {
            "content": "继续读取更多信息。",
            "tool_calls": [
                {"name": "run_python_code", "args": {"code": "print('second read')"}},
            ],
        },
        {"content": "读取完成。", "tool_calls": []},
    ])
    calls = []

    def fake_model(**kwargs):
        return next(responses)

    def fake_executor(tool_name, args):
        calls.append((tool_name, dict(args)))
        return "stdout only"

    request = FileTaskRequest(task="分析 Excel 数据", run_id="python_read_demo")
    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model, max_rounds=3).run(request))

    assert [name for name, _ in calls] == ["run_python_code", "run_python_code"]
    assert not any(
        event.type == "tool.finished" and event.payload.get("skipped")
        for event in events
    )


def test_file_task_runtime_blocks_python_pdf_text_extraction_and_guides_native_read():
    responses = iter([
        {
            "content": "我先用 Python 读 PDF。",
            "tool_calls": [
                {
                    "name": "run_python_code",
                    "args": {
                        "code": "from PyPDF2 import PdfReader\nreader = PdfReader('source.pdf')\nprint(reader.pages[0].extract_text())",
                    },
                },
            ],
        },
        {
            "content": "改用原生 PDF 读取。",
            "tool_calls": [
                {
                    "name": "parse_file_to_text",
                    "args": {"path": "source.pdf", "start_page": 1, "end_page": 3, "max_chars": 4000},
                },
            ],
        },
        {"content": "已完成读取。", "tool_calls": []},
    ])
    calls = []

    def fake_model(**kwargs):
        return next(responses)

    def fake_executor(tool_name, args):
        calls.append((tool_name, dict(args)))
        if tool_name == "parse_file_to_text":
            return "[Page 1]\nThe global rules of art"
        raise AssertionError(f"unexpected tool execution: {tool_name}")

    request = FileTaskRequest(
        task="读取 PDF 原文并对照译稿",
        run_id="pdf_python_guard_demo",
        files=[
            FileTaskFile(path="source.pdf", name="source.pdf", type="pdf"),
            FileTaskFile(path="draft.docx", name="draft.docx", type="docx", target=True),
        ],
    )
    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model, max_rounds=3).run(request))

    blocked = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("blocked")
    )

    assert all(name != "run_python_code" for name, _ in calls)
    assert any(
        name == "parse_file_to_text"
        and args.get("path") == "source.pdf"
        and args.get("start_page") == 1
        and args.get("end_page") == 3
        and args.get("max_chars") == 4000
        for name, args in calls
    )
    assert blocked.payload["tool_name"] == "run_python_code"
    assert blocked.payload["success"] is False
    assert "不要用 run_python_code 直接读取 PDF 文本" in blocked.payload["result_preview"]
    assert "parse_file_to_text" in blocked.payload["result_preview"]


def test_file_task_runtime_surfaces_python_image_artifacts_in_tool_finished():
    responses = iter([
        {
            "content": "先生成图表。",
            "tool_calls": [
                {"name": "run_python_code", "args": {"code": "print('ready')"}},
            ],
        },
        {"content": "图表已生成。", "tool_calls": []},
    ])

    def fake_model(**kwargs):
        return next(responses)

    def fake_executor(tool_name, args):
        assert tool_name == "run_python_code"
        return {
            "summary": "ready\n[1 image(s) generated]",
            "stdout": "ready",
            "stderr": "",
            "error": "",
            "files": {"chart.png": "ZmFrZQ=="},
            "_koto_created": [],
            "_koto_modified": [],
        }

    request = FileTaskRequest(task="基于当前数据生成图表", run_id="python_chart_artifact_demo")
    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model, max_rounds=2).run(request))

    tool_finished = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "run_python_code"
    )
    code_output = next(event for event in events if event.type == "code.output")

    assert tool_finished.payload["result_preview"] == "ready\n[1 image(s) generated]"
    assert tool_finished.payload["artifacts"] == [
        {"kind": "image", "name": "chart.png", "mime_type": "image/png", "data": "ZmFrZQ=="}
    ]
    assert code_output.payload["text"] == "ready"


def test_file_task_runtime_marks_duplicate_guard_as_skipped_not_failed():
    repeated_call = {"name": "read_sheet_data", "args": {"path": "sales.xlsx"}}
    responses = iter([
        {"content": "先读取。", "tool_calls": [repeated_call]},
        {"content": "再次读取。", "tool_calls": [repeated_call]},
    ])

    def fake_model(**kwargs):
        return next(responses)

    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: json.dumps({"rows": []}, ensure_ascii=False),
            model_client=fake_model,
            max_rounds=2,
        ).run(FileTaskRequest(task="分析 Excel 数据", run_id="duplicate_guard_demo"))
    )
    duplicate_guard = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "duplicate_guard"
    )

    assert duplicate_guard.payload["success"] is True
    assert duplicate_guard.payload["skipped"] is True
    assert "重复工具调用" in duplicate_guard.payload["result_preview"]


def test_file_task_runtime_treats_add_into_docx_as_write_intent():
    def fake_model(**kwargs):
        return {"content": "当前工具未写入。", "tool_calls": []}

    request = FileTaskRequest(task="将 xlsx 信息加入 docx", run_id="add_docx_demo")
    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(request))

    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert check_finished.payload["passed"] is False
    assert check_finished.payload["status"] == "no_file_change"
    assert run_finished.payload["completed_task"] is False


def test_file_task_runtime_treats_put_summary_into_new_slides_as_write_intent():
    def fake_model(**kwargs):
        return {"content": "我先读完了内容。", "tool_calls": []}

    request = FileTaskRequest(
        task="将内容总结并放到新的3页里",
        run_id="pptx_write_intent_demo",
        files=[FileTaskFile(path="AI Agent.pptx", name="AI Agent.pptx", type="pptx", target=True)],
    )
    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model, max_rounds=2).run(request))

    write_guard = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "write_guard"
    )
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert "add_pptx_slides" in write_guard.payload["result_preview"]
    assert "read_docx_content" in write_guard.payload["result_preview"]
    assert check_finished.payload["passed"] is False
    assert check_finished.payload["status"] == "no_file_change"
    assert run_finished.payload["completed_task"] is False


def test_file_task_runtime_treats_pptx_page_content_supplement_as_write_intent():
    def fake_model(**kwargs):
        return {"content": "我先读取每一页现有内容。", "tool_calls": []}

    request = FileTaskRequest(
        task="我要你每一页做的内容补充呢？",
        run_id="pptx_page_content_supplement_demo",
        files=[FileTaskFile(path="AI Agent.pptx", name="AI Agent.pptx", type="pptx", target=True)],
    )
    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model, max_rounds=2).run(request))

    run_started = events[0]
    write_guard = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "write_guard"
    )
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert run_started.payload["output_mode"] == "write"
    assert run_started.payload["task_family"] == "transform"
    assert run_started.payload["operation_kind"] == "write"
    assert "write_intent" in run_started.payload["reason_codes"]
    assert "write_pptx_slides" in write_guard.payload["result_preview"]
    assert check_finished.payload["passed"] is False
    assert check_finished.payload["status"] == "no_file_change"
    assert run_finished.payload["completed_task"] is False


def test_file_task_runtime_treats_write_back_text_prompt_as_write_intent():
    def fake_model(**kwargs):
        return {"content": "我先理解目标内容。", "tool_calls": []}

    request = FileTaskRequest(
        task="请把我选中的内容润色后直接写回当前 txt 文件",
        run_id="txt_write_back_demo",
        target_path="copilot_whitebox_demo.txt",
        selection="原始段落",
        selection_source="copilot_whitebox_demo.txt",
        files=[
            FileTaskFile(
                path="copilot_whitebox_demo.txt",
                name="copilot_whitebox_demo.txt",
                type="txt",
                target=True,
            )
        ],
    )
    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: "",
            model_client=fake_model,
            max_rounds=2,
        ).run(request)
    )

    run_started = events[0]
    write_guard = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "write_guard"
    )
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert run_started.payload["task_family"] == "transform"
    assert run_started.payload["operation_kind"] == "write"
    assert "write_intent" in run_started.payload["reason_codes"]
    assert "run_python_code" in write_guard.payload["result_preview"]
    assert check_finished.payload["passed"] is False
    assert check_finished.payload["status"] == "no_file_change"
    assert run_finished.payload["completed_task"] is False


def test_file_task_runtime_adds_pptx_slides_from_list_content(tmp_path):
    from pptx import Presentation

    pptx_path = tmp_path / "AI Agent.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    slide.shapes.title.text = "原始页"
    presentation.save(pptx_path)

    responses = iter([
        {
            "content": "我会把总结内容作为 3 页新 PPT 加入文件。",
            "tool_calls": [
                {
                    "name": "add_pptx_slides",
                    "args": {
                        "path": str(pptx_path),
                        "slides": [
                            {"title": "总结一", "content": ["市场需求明确", "替代成本是关键"]},
                            {"title": "总结二", "bullets": [{"text": "本地文件交付"}, {"content": "高质量生成"}]},
                            {"title": "总结三", "content": {"points": ["下一步做规格核验", "确认客户使用场景"]}},
                        ],
                    },
                }
            ],
        },
        {"content": "已新增 3 页总结。", "tool_calls": []},
    ])

    def fake_model(**kwargs):
        return next(responses)

    request = FileTaskRequest(
        task="将总结的内容作为3页新ppt加入",
        run_id="pptx_add_slides_demo",
        target_path=str(pptx_path),
        files=[FileTaskFile(path=str(pptx_path), name="AI Agent.pptx", type="pptx", content="原 PPT 内容", target=True)],
    )

    events = list(FileTaskRuntime(model_client=fake_model).run(request))
    add_finished = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "add_pptx_slides"
    )
    file_changed = next(event for event in events if event.type == "file.changed")
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert add_finished.payload["success"] is True
    assert file_changed.payload["path"] == str(pptx_path)
    assert check_finished.payload["status"] == "verified"
    assert run_finished.payload["completed_task"] is True

    saved = Presentation(str(pptx_path))
    all_text = "\n".join(shape.text for slide in saved.slides for shape in slide.shapes if hasattr(shape, "text"))
    assert len(saved.slides) == 4
    assert "总结一" in all_text
    assert "本地文件交付" in all_text
    assert "确认客户使用场景" in all_text


def test_file_task_runtime_executes_pptx_theme_design_tool(tmp_path):
    from pptx import Presentation

    pptx_path = tmp_path / "AI Agent.pptx"
    presentation = Presentation()
    for title, body in [
        ("原始标题", "第一点\n第二点"),
        ("增长计划", "市场\n产品\n交付"),
    ]:
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
    presentation.save(pptx_path)

    responses = iter([
        {
            "content": "我会直接调用 Koto 原生 PPTX 设计工具做统一主题和安全版式。",
            "tool_calls": [
                {
                    "name": "design_pptx_theme_layout",
                    "args": {
                        "path": str(pptx_path),
                        "style_brief": "科技感商业 BP",
                        "density": "balanced",
                    },
                }
            ],
        },
        {"content": "已完成统一主题与版式设计。", "tool_calls": []},
    ])

    def fake_model(**kwargs):
        return next(responses)

    request = FileTaskRequest(
        task="帮这个 pptx 做一套统一视觉风格和排版",
        run_id="pptx_theme_design_demo",
        target_path=str(pptx_path),
        files=[FileTaskFile(path=str(pptx_path), name="AI Agent.pptx", type="pptx", content="原 PPT 内容", target=True)],
    )

    events = list(FileTaskRuntime(model_client=fake_model).run(request))
    design_finished = next(
        event for event in events
        if event.type == "tool.finished" and event.payload.get("tool_name") == "design_pptx_theme_layout"
    )
    file_changed = next(event for event in events if event.type == "file.changed")
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert design_finished.payload["success"] is True
    assert file_changed.payload["path"] == str(pptx_path)
    assert file_changed.payload["operation"] == "design_pptx_theme_layout"
    assert file_changed.payload["slides_designed"] == 2
    assert file_changed.payload["theme_name"] == "科技深色"
    assert check_finished.payload["status"] == "verified"
    assert run_finished.payload["completed_task"] is True

    saved = Presentation(str(pptx_path))
    all_text = "\n".join(shape.text for slide in saved.slides for shape in slide.shapes if hasattr(shape, "text"))
    assert len(saved.slides) == 2
    assert "原始标题" in all_text
    assert "交付" in all_text


def test_file_task_runtime_prompt_tells_model_not_to_guess_sheet1():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(
        task="将 xlsx 信息加入 docx",
        run_id="sheet_prompt_demo",
        files=[
            FileTaskFile(path="销售台账.xlsx", name="销售台账.xlsx", type="xlsx"),
            FileTaskFile(path="雷鸟访谈问题.docx", name="雷鸟访谈问题.docx", type="docx", target=True),
        ],
    )

    prompt = runtime._build_system_prompt(request, request.files)

    assert "不要猜 Sheet1" in prompt
    assert "省略 sheet_name" in prompt
    assert "available_sheets" in prompt


def test_file_task_runtime_prompt_guides_chart_into_docx_via_real_image_write():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(
        task="把 Excel 数据画成图加入 docx",
        run_id="chart_docx_prompt_demo",
        files=[
            FileTaskFile(path="财务模型.xlsx", name="财务模型.xlsx", type="xlsx"),
            FileTaskFile(path="报告.docx", name="报告.docx", type="docx", target=True),
        ],
        target_path="报告.docx",
    )

    prompt = runtime._build_system_prompt(request, request.files)

    assert "insert_image_into_docx" in prompt
    assert "不要把图片描述文字写进文档代替真实插图" in prompt
    assert "dpi>=220" in prompt
    assert "axes.unicode_minus=False" in prompt


def test_file_task_runtime_prompt_routes_pptx_read_and_write_tools_correctly():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(
        task="将内容总结并放到新的3页里",
        run_id="pptx_prompt_demo",
        files=[FileTaskFile(path="AI Agent.pptx", name="AI Agent.pptx", type="pptx", target=True)],
    )

    prompt = runtime._build_system_prompt(request, request.files)

    assert "读取 PPTX 内容优先用 parse_file_to_text" in prompt
    assert "read_docx_content 只用于 DOCX" in prompt
    assert "新增 PPT 总结页时优先用 add_pptx_slides" in prompt


def test_file_task_runtime_prompt_forbids_python_pdf_text_reads_and_requires_windows():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(
        task="根据 PDF 原文润色 docx 译稿",
        run_id="pdf_prompt_demo",
        files=[
            FileTaskFile(path="source.pdf", name="source.pdf", type="pdf"),
            FileTaskFile(path="draft.docx", name="draft.docx", type="docx", target=True),
        ],
    )

    prompt = runtime._build_system_prompt(request, request.files)

    assert "读取 PDF 文本时只能使用 parse_file_to_text" in prompt
    assert "start_page/end_page" in prompt
    assert "不要用 run_python_code 调用 PyPDF2" in prompt
    assert "PDF 原文 + DOCX 译稿/润色/审校任务" in prompt


def test_file_task_runtime_has_specific_plan_copy_for_analysis_tools():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", model_client=lambda **kwargs: {})
    request = FileTaskRequest(task="对比文件并读取片段", run_id="analysis_plan_demo")

    assert runtime._tool_plan_title("compare_files") == "对比文件"
    assert runtime._tool_plan_title("read_file_range") == "读取文本片段"
    assert "比较维度" in runtime._tool_plan_description(
        "compare_files",
        {"file_paths": "a.md, b.md", "aspect": "content"},
        [],
        request,
    )
    assert "第 2 到 5 行" in runtime._tool_plan_description(
        "read_file_range",
        {"path": "notes.md", "start_line": 2, "end_line": 5},
        [],
        request,
    )


def test_file_task_event_serializes_as_sse_json():
    def fake_model(**kwargs):
        return {"content": "收到", "tool_calls": []}

    request = FileTaskRequest(task="读取选区", run_id="sse_demo", selection="hello")
    event = next(iter(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(request)))

    raw = event_to_sse(event)
    assert raw.startswith("data: ")
    assert raw.endswith("\n\n")
    payload = json.loads(raw.removeprefix("data: ").strip())
    assert payload["run_id"] == "sse_demo"
    assert payload["type"] == "run.started"


def test_file_task_tool_catalog_covers_mainstream_office_workflows():
    tool_names = {spec.name for spec in file_task_tool_specs()}
    workflows = supported_file_workflows()

    assert {"docx", "xlsx", "pptx", "pdf", "text", "sandbox"}.issubset(workflows)
    assert {"read_docx_content", "write_docx_content", "clear_docx_review_marks", "insert_image_into_docx", "read_sheet_data", "inspect_workbook_structure", "audit_financial_workbook", "write_sheet_data"}.issubset(tool_names)
    assert {"design_pptx_theme_layout", "write_pptx_slides", "add_pptx_slides", "parse_file_to_text", "run_python_code"}.issubset(tool_names)
    assert any("append images/charts" in item for item in workflows["docx"])
    assert any("clear review comments" in item for item in workflows["docx"])
    assert any("audit financial models" in item for item in workflows["xlsx"])


def test_file_task_runtime_system_prompt_guides_financial_workbook_audit_first():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "")
    request = FileTaskRequest(
        task="分析这个财务预测模型，找到问题",
        files=[FileTaskFile(path="forecast.xlsx", name="forecast.xlsx", type="xlsx")],
    )
    prompt = runtime._build_system_prompt(request, request.files)

    assert "audit_financial_workbook" in prompt
    assert "inspect_workbook_structure" in prompt
    assert "结构性缺陷/可复算性问题" in prompt


def test_file_task_tool_gateway_is_the_extension_entry_and_filters_allowlist():
    class FakeProvider:
        def __init__(self):
            self.calls = []

        def definitions(self):
            return [
                {"name": "parse_file_to_text", "description": "fake read", "parameters": {"type": "object"}},
                {"name": "shell_exec", "description": "must not leak", "parameters": {"type": "object"}},
            ]

        def allowed_names(self):
            return {"parse_file_to_text", "shell_exec"}

        def execute(self, tool_name, tool_args):
            self.calls.append((tool_name, tool_args))
            return f"provider:{tool_args.get('path', '')}"

    provider = FakeProvider()
    gateway = FileTaskToolGateway(context=FileTaskToolContext(workspace_root="workspace"), providers=[provider])

    assert gateway.allowed_names() == {"parse_file_to_text"}
    assert [definition["name"] for definition in gateway.definitions()] == ["parse_file_to_text"]
    assert gateway.execute("parse_file_to_text", {"path": "notes.md"}) == "provider:notes.md"
    assert provider.calls == [("parse_file_to_text", {"path": "notes.md"})]
    with pytest.raises(ValueError):
        gateway.execute("shell_exec", {})


def test_file_task_tool_gateway_filters_tools_by_task_file_type_context():
    class FakeProvider:
        def definitions(self):
            return [
                {"name": "read_docx_content", "description": "docx only", "parameters": {"type": "object"}},
                {"name": "parse_file_to_text", "description": "generic read", "parameters": {"type": "object"}},
                {"name": "add_pptx_slides", "description": "pptx write", "parameters": {"type": "object"}},
                {"name": "run_python_code", "description": "sandbox", "parameters": {"type": "object"}},
            ]

        def allowed_names(self):
            return {"read_docx_content", "parse_file_to_text", "add_pptx_slides", "run_python_code"}

        def execute(self, tool_name, tool_args):
            return "ok"

    gateway = FileTaskToolGateway(
        context=FileTaskToolContext(task_files=[{"path": "AI Agent.pptx", "type": "pptx"}]),
        providers=[FakeProvider()],
    )

    assert gateway.allowed_names() == {"parse_file_to_text", "add_pptx_slides", "run_python_code"}
    assert [definition["name"] for definition in gateway.definitions()] == [
        "parse_file_to_text",
        "add_pptx_slides",
        "run_python_code",
    ]


def test_file_task_runtime_uses_injected_tool_provider_boundary():
    model_tools = []

    class FakeProvider:
        def __init__(self):
            self.calls = []

        def definitions(self):
            return [{"name": "parse_file_to_text", "description": "fake read", "parameters": {"type": "object"}}]

        def allowed_names(self):
            return {"parse_file_to_text"}

        def execute(self, tool_name, tool_args):
            self.calls.append((tool_name, tool_args))
            return "provider context"

    def fake_model(**kwargs):
        model_tools.extend(kwargs["tools"])
        return {"content": "已读取 provider context", "tool_calls": []}

    provider = FakeProvider()
    request = FileTaskRequest(
        task="总结这个文件",
        run_id="provider_demo",
        files=[FileTaskFile(path="notes.md", name="notes.md", type="md")],
    )
    events = list(FileTaskRuntime(tool_provider=provider, model_client=fake_model).run(request))

    assert provider.calls == [("parse_file_to_text", {"path": "notes.md", "max_chars": 12000})]
    assert [tool["name"] for tool in model_tools] == ["parse_file_to_text"]
    assert events[-1].type == "run.finished"


def test_file_task_model_client_routes_local_and_cloud():
    calls = []

    class FakeClient(FileTaskModelClient):
        def _call_cloud(self, **kwargs):
            calls.append("cloud")
            return {"content": "cloud ok", "tool_calls": []}

        def _call_local(self, **kwargs):
            calls.append("local")
            return {"content": "local ok", "tool_calls": []}

    client = FakeClient()
    client.call(request=FileTaskRequest(task="t", model_mode="cloud"), messages=[], system="", tools=[])
    client.call(request=FileTaskRequest(task="t", model_mode="local"), messages=[], system="", tools=[])

    assert calls == ["cloud", "local"]


def test_file_task_model_client_routes_deepseek_cloud_provider(monkeypatch):
    from app.core.agent import file_task_model as file_task_model_module
    import app.core.llm.model_fallback as fallback_module
    import app.core.llm.provider_factory as provider_factory

    captured = {}

    class FakeProvider:
        pass

    class FakeFallbackExecutor:
        def generate_with_fallback(self, **kwargs):
            captured["fallback"] = kwargs
            return {"content": "deepseek ok", "tool_calls": []}

    def fake_get_llm_provider(**kwargs):
        captured["provider_kwargs"] = kwargs
        return FakeProvider()

    monkeypatch.setattr(
        file_task_model_module,
        "get_configured_cloud_model",
        lambda **kwargs: "deepseek-v4-pro",
    )
    monkeypatch.setattr(provider_factory, "get_llm_provider", fake_get_llm_provider)
    monkeypatch.setattr(fallback_module, "get_fallback_executor", lambda: FakeFallbackExecutor())

    client = FileTaskModelClient()
    response = client.call(
        request=FileTaskRequest(task="t", model_mode="deepseek", model_id="deepseek"),
        messages=[{"role": "user", "content": "hi"}],
        system="system",
        tools=[{"name": "parse_file_to_text"}],
    )

    assert response["content"] == "deepseek ok"
    assert captured["provider_kwargs"] == {"provider": "deepseek", "model": "deepseek-v4-pro"}
    assert captured["fallback"]["preferred_model"] == "deepseek-v4-pro"
    assert captured["fallback"]["task_type"] == "FILE_TASK"
    assert captured["fallback"]["system_instruction"] == "system"
    assert captured["fallback"]["tools"] == [{"name": "parse_file_to_text"}]


def test_file_task_model_client_passes_file_task_timeout_to_local_provider(monkeypatch):
    from app.core.agent import file_task_model as file_task_model_module
    import app.core.llm.ollama_llm_provider as ollama_module

    captured = {}

    class FakeOllamaProvider:
        def __init__(self, model=None):
            captured["model"] = model

        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return {"content": "local ok", "tool_calls": []}

    monkeypatch.setattr(ollama_module, "OllamaLLMProvider", FakeOllamaProvider)

    client = FileTaskModelClient()
    monkeypatch.setattr(client, "_is_local_available", lambda: True)

    response = client.call(
        request=FileTaskRequest(task="t", model_mode="local"),
        messages=[{"role": "user", "content": "hi"}],
        system="system",
        tools=[{"name": "parse_file_to_text"}],
    )

    assert response["content"] == "local ok"
    assert captured["model"] is None
    assert captured["call_timeout"] == file_task_model_module._FILE_TASK_LLM_CALL_TIMEOUT
    assert captured["system_instruction"] == "system"
    assert captured["tools"] == [{"name": "parse_file_to_text"}]
    assert captured["stream"] is False
    assert captured["temperature"] == 0.2


def test_file_task_model_client_prefers_file_task_model_route(monkeypatch):
    import sys
    import types

    fake_web = types.ModuleType("web")
    fake_app = types.ModuleType("web.app")
    fake_app.MODEL_MAP = {
        "CHAT": "chat-model",
        "FILE_TASK": "file-task-model",
    }
    monkeypatch.setitem(sys.modules, "web", fake_web)
    monkeypatch.setitem(sys.modules, "web.app", fake_app)

    client = FileTaskModelClient()

    assert client._cloud_model_id(FileTaskRequest(task="整理文件")) == "file-task-model"
