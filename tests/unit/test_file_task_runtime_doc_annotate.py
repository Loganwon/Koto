import json
from pathlib import Path

import pytest

from app.core.agent.file_task_contract import (
    FileTaskFile,
    FileTaskLedger,
    FileTaskRequest,
)
from app.core.agent.file_task_runtime import FileTaskRuntime


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
            FileTaskFile(
                path="interview.docx", name="interview.docx", type="docx", target=True
            ),
        ],
    )

    events = list(runtime.run(request))

    assert captured["request"] is request
    assert captured["workspace_root"] == "C:/runtime-workspace"
    assert captured["gemini_client"] == "gemini-client"
    plan_checked = next(event for event in events if event.type == "plan.checked")
    assert plan_checked.payload["passed"] is True
    classified = next(event for event in events if event.type == "task.classified")
    classification = classified.payload["classification"]
    assert classification["execution_mode"] == "doc_annotate_bridge"
    assert classification["selected_recipe"] == "pdf_docx_review_bridge"
    run_started = next(event for event in events if event.type == "run.started")
    assert run_started.payload["mode"] == "whitebox_v1"
    assert run_started.payload["execution_mode"] == "doc_annotate_bridge"
    assert events[-1].payload["completed_task"] is True
    assert events[-1].payload["execution_mode"] == "doc_annotate_bridge"
    assert (
        events[-1].payload["completion_contract"]["contract_id"]
        == "pdf_docx_review_bridge"
    )
    assert events[-1].payload["completion_contract"]["write_required"] is True
    assert (
        "annotate_file"
        in events[-1].payload["completion_contract"]["required_operations"]
    )
    assert (
        events[-1].payload["workflow_state"]["mainline"]["selected_recipe"]
        == "pdf_docx_review_bridge"
    )


def test_file_task_runtime_routes_single_docx_annotation_to_doc_annotate_bridge(
    monkeypatch,
):
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
        files=[
            FileTaskFile(
                path="interview.docx", name="interview.docx", type="docx", target=True
            )
        ],
    )

    events = list(
        FileTaskRuntime(
            tool_executor=unexpected_executor,
            model_client=unexpected_model,
            max_rounds=2,
        ).run(request)
    )

    assert captured["request"] is request
    assert captured["workspace_root"] == ""
    assert captured["gemini_client"] is None
    plan_checked = next(event for event in events if event.type == "plan.checked")
    assert plan_checked.payload["passed"] is True
    classified = next(event for event in events if event.type == "task.classified")
    classification = classified.payload["classification"]
    assert classification["execution_mode"] == "doc_annotate_bridge"
    assert classification["selected_recipe"] == "single_docx_review_bridge"
    run_started = next(event for event in events if event.type == "run.started")
    assert run_started.payload["mode"] == "whitebox_v1"
    assert run_started.payload["execution_mode"] == "doc_annotate_bridge"
    assert events[-1].payload["completed_task"] is True
    assert events[-1].payload["execution_mode"] == "doc_annotate_bridge"
    assert events[-1].payload["summary"] == "已切入单 DOCX 审校批注桥接流程。"
    assert (
        events[-1].payload["completion_contract"]["contract_id"]
        == "single_docx_review_bridge"
    )
    assert events[-1].payload["completion_contract"]["write_required"] is True
    assert (
        "annotate_file"
        in events[-1].payload["completion_contract"]["required_operations"]
    )
    assert (
        events[-1].payload["workflow_state"]["mainline"]["selected_recipe"]
        == "single_docx_review_bridge"
    )


def test_file_task_runtime_does_not_external_fallback_after_doc_annotate_bridge_failure(
    monkeypatch,
):
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
            return "retired_external"

        def call(self, **kwargs):
            request = kwargs["request"]
            messages = kwargs["messages"]
            tools = kwargs.get("tools", [])
            system = str(kwargs.get("system", ""))

            # Adjudicator calls: no tools, adjudicator system prompt
            if not tools and "任务意图裁判" in system:
                return {
                    "content": json.dumps(
                        {
                            "intent": "edit_file",
                            "confidence": 0.92,
                            "should_write": True,
                            "should_use_annotate_bridge": True,
                            "reason": "用户要求批注DOCX文件",
                        },
                        ensure_ascii=False,
                    ),
                    "tool_calls": [],
                }

            self.options_seen.append(dict(request.options or {}))

            if any(
                message.get("role") == "function"
                and message.get("name") == "annotate_file"
                for message in messages
            ):
                return {
                    "content": "Retired planner 已完成批注写回。",
                    "tool_calls": [],
                    "_planner": {
                        "backend": "retired_external",
                        "source": "external",
                        "policy": "explicit_backend",
                        "transport": "embedded",
                        "reason": str(
                            request.options.get("planner_runtime_reason") or ""
                        ),
                    },
                }

            return {
                "content": "Retired planner 重新规划并执行批注写回。",
                "tool_calls": [
                    {
                        "id": "retired_external_annotate_docx",
                        "name": "annotate_file",
                        "args": {
                            "path": "interview.docx",
                            "annotations": "[]",
                            "requirement": "将你觉得写得不好的地方批注出来",
                        },
                    }
                ],
                "_planner": {
                    "backend": "retired_external",
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
        files=[
            FileTaskFile(
                path="interview.docx",
                name="interview.docx",
                type="docx",
                content="正文",
                target=True,
            )
        ],
    )

    events = list(
        FileTaskRuntime(
            tool_executor=fake_executor, model_client=model_client, max_rounds=4
        ).run(request)
    )

    run_finished = next(
        event for event in reversed(events) if event.type == "run.finished"
    )

    assert any(
        event.payload.get("mode") == "whitebox_v1"
        and event.payload.get("execution_mode") == "doc_annotate_bridge"
        for event in events
        if event.type == "run.started"
    )
    assert run_finished.payload.get("mode") == "whitebox_v1"
    assert run_finished.payload.get("execution_mode") == "doc_annotate_bridge"
    assert run_finished.payload["completed_task"] is False
    assert not any(event.type == "planner.selected" for event in events)
    assert not any(event.type == "planner.fallback" for event in events)
    assert model_client.options_seen == []


@pytest.mark.parametrize(
    "task_text",
    [
        "取消docx里面所有批注",
        "将docx里面的标注都移除",
    ],
)
def test_doc_annotate_bridge_does_not_route_docx_clear_comment_requests(task_text):
    import app.core.agent.file_task_doc_annotate_bridge as bridge

    request = FileTaskRequest(
        task=task_text,
        run_id="clear_docx_comments_demo",
        target_path="interview.docx",
        files=[
            FileTaskFile(
                path="interview.docx", name="interview.docx", type="docx", target=True
            )
        ],
    )

    assert bridge.looks_like_docx_review_clear_request(request.task) is True
    assert bridge.should_route_request(request) is False


def test_doc_annotate_bridge_does_not_route_plain_docx_polish_request():
    import app.core.agent.file_task_doc_annotate_bridge as bridge
    from app.core.agent.file_task_recipes import select_task_recipe

    request = FileTaskRequest(
        task="润色这篇文章",
        run_id="plain_docx_polish_demo",
        target_path="humanise!_revised.docx",
        files=[
            FileTaskFile(
                path="humanise!_revised.docx",
                name="humanise!_revised.docx",
                type="docx",
                target=True,
            )
        ],
    )

    runtime = FileTaskRuntime()
    recipe = select_task_recipe(request, request.files, write_intent=True)

    assert bridge.looks_like_direct_docx_rewrite_request(request.task) is True
    assert bridge.should_route_request(request) is False
    assert runtime._is_docx_annotation_request(request) is False
    assert recipe is not None
    assert recipe.recipe.id == "docx_polish_writeback"


def test_pdf_docx_review_recipe_does_not_require_translation_or_source_words():
    import app.core.agent.file_task_doc_annotate_bridge as bridge

    runtime = FileTaskRuntime()
    request = FileTaskRequest(
        task="帮我校对这份文档，把不通顺的地方标注出来",
        run_id="pdf_docx_review_lenient_markers",
        target_path="draft.docx",
        files=[
            FileTaskFile(path="source.pdf", name="source.pdf", type="pdf"),
            FileTaskFile(
                path="draft.docx", name="draft.docx", type="docx", target=True
            ),
        ],
    )

    classification = runtime._classify_request(request, runtime._context_files(request))

    assert bridge.should_route_request(request) is True
    assert classification.execution_mode == "doc_annotate_bridge"
    assert classification.selected_recipe == "pdf_docx_review_bridge"


def test_legacy_doc_target_does_not_enter_docx_review_bridge():
    import app.core.agent.file_task_doc_annotate_bridge as bridge

    runtime = FileTaskRuntime()
    request = FileTaskRequest(
        task="Please comment on the places that need revision.",
        run_id="doc_suffix_docx_review_bridge",
        target_path="draft.doc",
        files=[
            FileTaskFile(path="draft.doc", name="draft.doc", type="doc", target=True),
        ],
    )

    classification = runtime._classify_request(request, runtime._context_files(request))

    assert runtime._request_has_file_type(request, "docx") is True
    assert bridge.should_route_request(request) is False
    assert classification.execution_mode != "doc_annotate_bridge"


def test_docx_review_bridge_understands_natural_problem_markers():
    import app.core.agent.file_task_doc_annotate_bridge as bridge

    request = FileTaskRequest(
        task="请批注这份文稿，把问题标出来",
        run_id="natural_docx_review_marker",
        target_path="draft.docx",
        files=[
            FileTaskFile(
                path="draft.docx", name="draft.docx", type="docx", target=True
            ),
        ],
    )

    assert bridge.should_route_request(request) is True


def test_explicit_docx_annotation_still_controls_bridge_mainline():
    runtime = FileTaskRuntime()
    request = FileTaskRequest(
        task="Please annotate this document and add comments to the problematic parts.",
        run_id="explicit_annotation_authority",
        target_path="draft.docx",
        files=[
            FileTaskFile(path="draft.docx", name="draft.docx", type="docx", target=True)
        ],
    )

    classification = runtime._normalize_mainline_contract(
        request,
        request.files,
        runtime._classify_request(request, request.files),
    )

    assert classification.write_intent is True
    assert classification.docx_annotation_request is True
    assert classification.execution_mode == "doc_annotate_bridge"
    assert classification.selected_recipe == "single_docx_review_bridge"
    assert (
        "mainline_contract:docx_annotation_demoted" not in classification.reason_codes
    )


def test_doc_annotate_bridge_does_not_resume_plain_continue_optimize_after_failed_polish():
    import app.core.agent.file_task_doc_annotate_bridge as bridge

    request = FileTaskRequest(
        task="继续优化",
        run_id="plain_continue_optimize_demo",
        target_path="humanise!_revised.docx",
        files=[
            FileTaskFile(
                path="humanise!_revised.docx",
                name="humanise!_revised.docx",
                type="docx",
                target=True,
            )
        ],
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "improve",
                "previous_task_mode": "doc_annotate_bridge",
                "previous_task_request": "润色这篇文章",
                "previous_task_summary": "已将 0 条修订写回 humanise!_revised.docx。",
            }
        },
    )

    assert bridge.should_route_request(request) is False


def test_doc_annotate_bridge_treats_zero_applied_writeback_as_incomplete(
    monkeypatch, tmp_path
):
    import app.core.agent.file_task_doc_annotate_bridge as bridge
    import web.document_feedback as feedback_module

    docx_path = tmp_path / "humanise!_revised.docx"
    docx_path.write_bytes(b"PK\x03\x04")

    class FakeFeedback:
        default_model_id = "gemini-2.5-pro"

        def __init__(self, gemini_client=None):
            self.gemini_client = gemini_client

        def full_annotation_loop_streaming(self, *args, **kwargs):
            yield {"stage": "reading_complete", "detail": "44 段，6427 字"}
            yield {"stage": "analysis_complete", "detail": "找到 1 处修改"}
            yield {
                "stage": "complete",
                "result": {
                    "success": True,
                    "revised_file": str(docx_path),
                    "applied": 0,
                    "message": "已将 0 条修订写回 humanise!_revised.docx。",
                },
            }

    monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

    request = FileTaskRequest(
        task="请批注写得不好的地方",
        run_id="zero_applied_docx_review_demo",
        target_path=str(docx_path),
        files=[
            FileTaskFile(
                path=str(docx_path),
                name=docx_path.name,
                type="docx",
                target=True,
            )
        ],
    )

    events = list(bridge.stream_request(request, workspace_root=str(tmp_path)))
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert not any(event.type == "file.changed" for event in events)
    assert check_finished.payload["passed"] is False
    assert run_finished.type == "run.finished"
    assert run_finished.payload["completed_task"] is False
    assert run_finished.payload["annotations_added"] == 0


def test_doc_annotate_bridge_does_not_route_two_docx_compare_annotation_request():
    import app.core.agent.file_task_doc_annotate_bridge as bridge

    request = FileTaskRequest(
        task="对比这两份文件，找出他们有区别的地方标注出来",
        run_id="docx_compare_annotation_bridge_guard",
        files=[
            FileTaskFile(path="humanise!.docx", name="humanise!.docx", type="docx"),
            FileTaskFile(
                path="humanise!_revised.docx",
                name="humanise!_revised.docx",
                type="docx",
                target=True,
            ),
        ],
        target_path="humanise!_revised.docx",
    )

    assert bridge.looks_like_multi_file_compare_request(request) is True
    assert bridge.should_route_request(request) is False


@pytest.mark.parametrize(
    "task_text",
    [
        "取消docx里面所有批注",
        "将docx里面的标注都移除",
    ],
)
def test_file_task_runtime_classifies_docx_clear_comment_request_as_write_not_annotation(
    task_text,
):
    runtime = FileTaskRuntime(
        tool_executor=lambda name, args: "",
        model_client=lambda **kwargs: {"content": "ok", "tool_calls": []},
    )
    request = FileTaskRequest(
        task=task_text,
        run_id="clear_docx_comments_classification",
        target_path="interview.docx",
        files=[
            FileTaskFile(
                path="interview.docx", name="interview.docx", type="docx", target=True
            )
        ],
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


def test_file_task_runtime_direct_docx_polish_writeback_is_not_annotation_bridge():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "")
    request = FileTaskRequest(
        task="润色这个docx并写回当前docx",
        target_path="draft.docx",
        files=[
            FileTaskFile(path="draft.docx", name="draft.docx", type="docx", target=True)
        ],
    )

    classification = runtime._classify_request(request, request.files)

    assert classification.task_family == "polish"
    assert classification.operation_kind == "write"
    assert classification.output_mode == "write"
    assert classification.selected_recipe == "docx_polish_writeback"
    assert classification.docx_annotation_request is False
    assert "polish_request" in classification.reason_codes
    assert "docx_annotation_request" not in classification.reason_codes


def test_file_task_runtime_classifies_followup_improve_from_previous_annotation_metadata():
    def fake_model(**kwargs):
        return {"content": "继续优化上一轮批注结果", "tool_calls": []}

    request = FileTaskRequest(
        task="请继续优化上一轮结果",
        run_id="followup_classification_demo",
        current_file=FileTaskFile(
            path="translation.docx",
            name="translation.docx",
            type="docx",
            content="现有译稿",
        ),
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

    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: "", model_client=fake_model
        ).run(request)
    )
    run_started = events[0]

    assert run_started.payload["request_kind"] == "followup"
    assert run_started.payload["task_family"] == "annotate"
    assert run_started.payload["operation_kind"] == "annotate"
    assert run_started.payload["docx_annotation_request"] is True
    assert (
        "followup_previous_task_family:annotate" in run_started.payload["reason_codes"]
    )
    assert (
        "followup_previous_execution_mode:annotate_tool_loop"
        in run_started.payload["reason_codes"]
    )


def test_doc_annotate_bridge_is_hidden_behind_boundary():
    agent_files = Path("app/core/agent").glob("*.py")
    direct_refs = []
    for path in agent_files:
        if path.name == "file_task_doc_annotate_bridge.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "file_task_doc_annotate_bridge" in source:
            direct_refs.append(path.name)

    assert direct_refs == ["file_task_doc_annotate_boundary.py"]


def test_file_task_runtime_routes_doc_annotate_bridge_through_runner():
    runtime_source = Path("app/core/agent/file_task_runtime.py").read_text(
        encoding="utf-8"
    )
    runner_source = Path("app/core/agent/file_task_doc_annotate_runner.py").read_text(
        encoding="utf-8"
    )

    assert "FileTaskDocAnnotateRunner(self).stream_bridge_execution" in runtime_source
    assert "file_task_doc_annotate_boundary.stream_bridge_request" in runner_source
    assert 'execution_mode": "doc_annotate_bridge"' in runner_source
    assert "file_task_doc_annotate_boundary.stream_bridge_request" not in runtime_source


def test_doc_annotate_intent_rules_are_outside_legacy_bridge():
    bridge_source = Path("app/core/agent/file_task_doc_annotate_bridge.py").read_text(
        encoding="utf-8"
    )
    boundary_source = Path(
        "app/core/agent/file_task_doc_annotate_boundary.py"
    ).read_text(encoding="utf-8")
    intent_source = Path("app/core/agent/file_task_doc_annotate_intent.py").read_text(
        encoding="utf-8"
    )

    assert "file_task_doc_annotate_intent" in bridge_source
    assert "file_task_doc_annotate_intent" in boundary_source
    assert "def should_use_doc_annotate_bridge_execution" not in bridge_source
    assert "_DOCX_CLEAR_REVIEW_REQUEST_PATTERNS" not in bridge_source
    assert "def should_use_doc_annotate_bridge_execution" in intent_source
    assert "_DOCX_CLEAR_REVIEW_REQUEST_PATTERNS" in intent_source


def test_doc_annotate_event_formatters_are_outside_legacy_bridge():
    bridge_source = Path("app/core/agent/file_task_doc_annotate_bridge.py").read_text(
        encoding="utf-8"
    )
    event_source = Path("app/core/agent/file_task_doc_annotate_events.py").read_text(
        encoding="utf-8"
    )

    assert "file_task_doc_annotate_events" in bridge_source
    assert "def _build_review_progress_payload" not in bridge_source
    assert "def _tool_result_from_bridge_payload" not in bridge_source
    assert "def build_review_progress_payload" in event_source
    assert "def tool_result_from_bridge_payload" in event_source
