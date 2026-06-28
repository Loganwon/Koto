# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _body_between(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def test_workspace_chat_has_single_file_task_entrypoint() -> None:
    source = _read("web/src/workspace/ai-review.ts")
    body = _body_between(
        source,
        "export function sendMessage(): void {",
        "// ── Quick action dispatcher ──",
    )

    assert "taskDispatcher.dispatchMessage({" in body
    assert "streamTaskFlow" not in body
    assert "/api/editor/ai/task-stream" not in body
    assert "/api/workspace/ai/route-intent" not in body


def test_workspace_uses_bundled_ts_assets_without_legacy_static_entrypoints() -> None:
    assets = _read("web/templates/_workspace_asset_scripts.html")
    bundle_entry = _read("web/src/bundles/workspace.ts")

    assert "js/build/workspace-bundle.js" in assets
    assert "workspace-assistant.js" not in assets
    assert "workspace-task-dispatcher.js" not in assets
    assert "import '../workspace/ai-review';" in bundle_entry
    assert "import '../workspace/task-dispatcher';" in bundle_entry
    assert not (ROOT / "web/static/js/workspace-assistant.js").exists()
    assert not (ROOT / "web/static/js/workspace-task-dispatcher.js").exists()
    assert not (ROOT / "web/static/js/src/workspace-assistant.js").exists()
    assert not (ROOT / "web/static/js/src/workspace-task-dispatcher.js").exists()


def test_workspace_page_routes_are_registered_without_legacy_page_shell() -> None:
    pages = _read("web/blueprints/pages.py")
    blueprints = _read("web/app_blueprints.py")

    assert '@pages_bp.route("/")' in pages
    assert '@pages_bp.route("/app")' in pages
    assert '@pages_bp.route("/workspace-assistant")' in pages
    assert "redirect(target, code=302)" in pages
    assert 'render_template("index.html", initial_theme=_get_initial_theme())' in pages
    assert '("web.blueprints.pages", "pages_bp", None, "Pages")' in blueprints
    assert "workspace-assistant.js" not in pages


def test_workspace_dispatcher_uses_model_primary_intent_before_task_stream() -> None:
    source = _read("web/src/workspace/task-dispatcher.ts")
    route_body = _body_between(
        source,
        "async function runWorkspaceModelRoutedTask(context: TaskContext): Promise<any> {",
        "  registerMessageRoute({",
    )
    payload_body = _body_between(
        source,
        "function buildWhiteboxTaskPayload(",
        "  function finalizeExplicitTaskPayload(",
    )

    assert "_csrfFetch('/api/workspace/ai/route-intent'" in source
    assert "routeDecision = await resolveWorkspaceRouteIntent(context);" in route_body
    assert route_body.index("resolveWorkspaceRouteIntent") < route_body.rindex(
        "return runTaskFlowRoute"
    )
    assert "function fileTaskRouteDecision(" in source
    assert "route_source: routeSource" in source
    assert "keyword_policy: 'hint_only'" in source
    assert "fileTaskRouteDecision('explicit_task_payload')" in route_body
    assert "fileTaskRouteDecision('frontend_file_context_guard', routeDecision)" in route_body
    assert "overrideOptions.enable_ai_intent_adjudicator = true;" in payload_body
    assert (
        "overrideOptions.router_policy = overrideOptions.router_policy || "
        "'model_primary_intent';"
    ) in payload_body


def test_workspace_direct_response_is_locked_to_chat_stream() -> None:
    dispatcher = _read("web/src/workspace/task-dispatcher.ts")
    chat_stream_body = _body_between(
        dispatcher,
        "async function streamWorkspaceChatRoute(context: TaskContext, routeDecision: Record<string, any>): Promise<any> {",
        "  function runTaskFlowRoute(",
    )
    route_body = _body_between(
        dispatcher,
        "async function runWorkspaceModelRoutedTask(context: TaskContext): Promise<any> {",
        "  registerMessageRoute({",
    )
    orchestrator = _body_between(
        _read("web/services/chat_stream/orchestrator.py"),
        "SmartDispatcher.analyze() + task type resolution",
        "Workflow routing",
    )

    assert "/api/workspace/ai/direct-response" not in dispatcher
    assert "_csrfFetch('/api/chat/stream'" in chat_stream_body
    assert "locked_task: lockedTask" in chat_stream_body
    assert "skills_enabled: false" in chat_stream_body
    assert "function isDirectWorkspaceResponse(" in dispatcher
    assert "if (isDirectWorkspaceResponse(routeDecision))" in route_body
    assert "if locked_task:" in orchestrator
    assert orchestrator.index("if locked_task:") < orchestrator.index(
        "task_type, route_method, context_info = SmartDispatcher.analyze("
    )


def test_task_stream_backend_does_not_call_legacy_agents_or_router() -> None:
    source = _read("web/file_task_stream.py")
    forbidden = [
        "SmartDispatcher",
        "UnifiedAgent",
        "SkillAutoMatcher",
        "KotoAgentLoop",
        "app.core.routing",
    ]

    assert "FileTaskRuntime(" in source
    for token in forbidden:
        assert token not in source


def test_file_task_tool_gateway_is_only_a_tool_boundary() -> None:
    source = _read("app/core/agent/file_task_tool_gateway.py")
    forbidden = [
        "SmartDispatcher",
        "FileTaskRuntime(",
        "SkillAutoMatcher",
        "KotoAgentLoop",
        "route_intent",
        "task.classified",
    ]

    assert "file_task_tool_specs" in source
    assert "is_file_task_tool(name)" in source
    assert "def execute(self, tool_name: str, tool_args: Dict[str, Any])" in source
    for token in forbidden:
        assert token not in source


def test_runtime_records_decision_and_supervisor_verification_per_tool_step() -> None:
    source = _read("app/core/agent/file_task_runtime.py")

    assert '"decision.made"' in source
    assert '"supervisor.step_verified"' in source
    assert '"check.finished"' in source
    assert '"supervisor.verified"' in source
    assert source.index('"decision.made"') < source.index('"supervisor.step_verified"')


def test_history_records_show_structured_task_chain_verification() -> None:
    dispatcher = _read("web/src/workspace/task-dispatcher.ts")
    conversation = _read("web/src/workspace/conversation.ts")
    sessions = _read("web/blueprints/sessions.py")

    assert "function taskCardTestStructure(" in dispatcher
    assert "metadata.test_structure = testStructure;" in dispatcher
    assert "schema: 'koto_ai_task_chain_test_v1'" in dispatcher
    assert "final_summary: finalSummary" in dispatcher
    assert "工作区输入框 -> AI 意图判断 -> 文件任务流 -> 监管执行" in dispatcher
    assert "function renderTestStructure(" in conversation
    assert "执行过程" in conversation
    assert "本轮结论：" in conversation
    assert "wa-task-process-step" in conversation
    assert "wa-task-final-answer" in conversation
    assert "technical_entrypoint" in conversation
    assert "turn.test_structure" in conversation
    assert '"test_structure"' in sessions

    task_runner = _read("web/src/workspace/task-runner.ts")
    assert "function renderTaskFinalReport(" in task_runner
    assert "function compactTerminalProcess(" in task_runner
    assert "(window as any)._waRenderMarkdown" in task_runner
    assert "wa-task-final-report" in task_runner
    assert "const auditHtml = supervisorAuditHtml(data);" in task_runner
    assert "taskResultActionsHtml(card) + auditHtml + '<div class=\"wa-task-final-report\">' + renderTaskFinalReport(visibleSummary)" in task_runner
    assert "wa-task-step-detail" in task_runner
    assert "data-role=\"process\"" in task_runner
    assert "handleEvent_supervisor_step_verified" in task_runner
    assert "'supervisor.step_verified': handleEvent_supervisor_step_verified" in task_runner


def test_compact_task_card_keeps_process_steps_visible_before_summary() -> None:
    css = _read("web/static/css/workspace.css")

    hidden_blocks = re.findall(r"\{[^{}]*display\s*:\s*none\s*!important[^{}]*\}", css)
    assert not any('[data-role="plan"]' in block for block in hidden_blocks)
    assert not any('[data-role="steps"]' in block for block in hidden_blocks)

    task_runner = _body_between(
        _read("web/src/workspace/task-runner.ts"),
        "function makeRunCard(",
        "function ensureTaskLiveProgressHost()",
    )
    process_index = task_runner.index('data-role="process"')
    summary_index = task_runner.index('data-role="summary"')
    assert process_index < summary_index
