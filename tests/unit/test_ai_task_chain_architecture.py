# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

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
    build_script = _read("web/scripts/build-bundles.mjs")

    assert "js/build/workspace-bundle.js" in assets
    assert "workspace-assistant.js" not in assets
    assert "workspace-task-dispatcher.js" not in assets
    assert "range(100000,999999)|random" not in assets
    assert "asset_url('vendor/split.min.js')" in assets
    assert "asset_url('js/build/workspace-bundle.js')" in assets
    assert "review-bundle.js" not in assets
    assert assets.index("split.min.js") < assets.index("workspace-bundle.js")
    assert "pure: ['console.debug']" in build_script
    assert "import '../workspace/ai-review';" in bundle_entry
    assert "import '../workspace/task-dispatcher';" in bundle_entry
    assert not (ROOT / "web/static/js/workspace-assistant.js").exists()
    assert not (ROOT / "web/static/js/workspace-task-dispatcher.js").exists()
    assert not (ROOT / "web/static/js/src/workspace-assistant.js").exists()
    assert not (ROOT / "web/static/js/src/workspace-task-dispatcher.js").exists()


def test_desktop_ai_entry_has_no_classic_composer_compatibility_path() -> None:
    sources = {
        "index": _read("web/templates/index.html"),
        "main": _read("web/src/app/main.ts"),
        "active_composer": _read("web/src/shared/active-composer.ts"),
        "frontend_observer": _read("web/src/mcp/frontend-observer.ts"),
        "tarot": _read("web/src/extras/tarot-picker.ts"),
        "skill_ui": _read("web/src/skills/skill-ui.ts"),
        "desktop_css": _read("web/static/css/style.css"),
    }

    assert sources["index"].count('id="wa-user-input"') == 1
    assert sources["index"].count('id="wa-send-btn"') == 1
    for source in sources.values():
        assert "messageInput" not in source
        assert "legacyFallback" not in source
    assert 'id="sendBtn"' not in sources["index"]
    assert "getElementById('sendBtn')" not in sources["main"]
    assert "window as any).sendMessage" not in sources["main"]
    assert "delegateHiddenLegacySendToWorkspace" not in sources["main"]
    assert ".chat-input-form" not in sources["desktop_css"]
    assert ".chat-input-container" not in sources["desktop_css"]


def test_unified_workspace_shell_has_no_hidden_legacy_sidebar_surface() -> None:
    index = _read("web/templates/index.html")
    workspace_css = _read("web/static/css/workspace.css")

    assert "sidebar-compat" not in index
    assert "sidebar-compat" not in workspace_css
    # The session bridge has null-safe guards, so deleting the unreachable
    # compatibility surface cannot resurrect a second sidebar at runtime.
    session_bridge = _read("web/src/app/session-bridge.ts")
    assert "if (!container) return;" in session_bridge
    assert "if (!select) return;" in session_bridge


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
    routing = _read("web/src/workspace/task-routing-decision.ts")
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
    assert "export function deterministicWorkspaceRouteDecision(" in routing
    assert (
        "const deterministicRoute = deterministicWorkspaceRouteDecision({" in route_body
    )
    assert route_body.index("deterministicWorkspaceRouteDecision") < route_body.index(
        "resolveWorkspaceRouteIntent"
    )
    assert "const EXPLICIT_FILE_REFERENCE_RE" in routing
    assert "function mentionsExplicitTaskFile(" in routing
    assert "frontend_deterministic_explicit_file_reference" in routing
    assert (
        "mentionsExplicitTaskFile(text) && FILE_TASK_CONTEXT_CUE_RE.test(text)"
        in routing
    )
    assert (
        "routeSource === 'frontend_deterministic_explicit_file_reference'"
    ) in routing
    assert "routeDecision = await resolveWorkspaceRouteIntent(context);" in route_body
    assert route_body.index("resolveWorkspaceRouteIntent") < route_body.rindex(
        "return runTaskFlowRoute"
    )
    assert "export function fileTaskRouteDecision(" in routing
    assert "route_source: routeSource" in routing
    assert "keyword_policy: 'hint_only'" in routing
    assert "skip_ai_intent_adjudicator" in routing
    assert "fileTaskRouteDecision('explicit_task_payload')" in route_body
    assert (
        "fileTaskRouteDecision('frontend_file_context_guard', routeDecision)"
        in route_body
    )
    assert "overrideOptions.enable_ai_intent_adjudicator = true;" not in payload_body
    assert "overrideOptions.disable_ai_intent_adjudicator = true;" in payload_body
    assert "delete overrideOptions.enable_ai_intent_adjudicator;" in payload_body
    assert (
        "overrideOptions.router_policy = overrideOptions.router_policy || "
        "'model_primary_intent';"
    ) in payload_body


def test_workspace_route_intent_has_deterministic_fast_path_before_model() -> None:
    editor_ai = _read("web/blueprints/editor_ai.py")
    route_endpoint = _body_between(
        editor_ai,
        "def workspace_ai_route_intent():",
        '\n\n@editor_ai_bp.route("/api/editor/ai/stream", methods=["POST"])',
    )

    assert "/api/workspace/ai/direct-response" not in editor_ai
    assert "def workspace_ai_direct_response(" not in editor_ai
    assert "def _deterministic_workspace_route(data: dict) -> dict | None:" in editor_ai
    assert 'source="deterministic:file_context"' in editor_ai
    assert "_EXPLICIT_FILE_REFERENCE_RE" in editor_ai
    assert "def _workspace_mentions_explicit_task_file(text: str) -> bool:" in editor_ai
    assert 'source="deterministic:explicit_file_reference"' in editor_ai
    assert (
        "_workspace_mentions_explicit_task_file(text) and _FILE_CONTEXT_TASK_RE.search(text)"
        in editor_ai
    )
    assert '"skip_ai_intent_adjudicator": True' in editor_ai
    assert (
        "deterministic_route = _deterministic_workspace_route(data)" in route_endpoint
    )
    assert "started_at = time.perf_counter()" in route_endpoint
    assert '"route_decision_ms"' in route_endpoint
    assert '"route_path"' in route_endpoint
    assert route_endpoint.index(
        "_deterministic_workspace_route"
    ) < route_endpoint.index("_model_workspace_route")


def test_workspace_direct_response_is_locked_to_chat_stream() -> None:
    dispatcher = _read("web/src/workspace/task-dispatcher.ts")
    routing = _read("web/src/workspace/task-routing-decision.ts")
    direct_chat = _read("web/src/workspace/task-direct-chat.ts")
    editor_ai = _read("web/blueprints/editor_ai.py")
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
    assert "'system_action'" in direct_chat
    assert '"system_action"' in editor_ai
    assert "WHITELISTED_APP_LAUNCH_RE" in routing
    assert "WHITELISTED_APP_LAUNCH_RE.test(text)" in routing
    assert 'if normalized == "SYSTEM":' in editor_ai
    assert 'return "system_action"' in editor_ai
    assert "createWorkspaceChatStreamer" in dispatcher
    assert "deps.csrfFetch('/api/chat/stream'" in direct_chat
    assert "locked_task: routeContract.lockedTask" in direct_chat
    assert "lockedTask: 'SYSTEM'" in direct_chat
    assert "skills_enabled: false" in direct_chat
    assert "export function isDirectWorkspaceResponse(" in routing
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
    runtime_source = _read("app/core/agent/file_task_runtime.py")
    execution_source = _read("app/core/agent/file_task_execution_loop.py")
    finalization_source = _read("app/core/agent/file_task_finalization.py")

    assert "FileTaskExecutionLoop(self).stream(" in runtime_source
    assert "FileTaskFinalizationPhase(self).stream(" in runtime_source
    assert '"decision.made"' in execution_source
    assert '"supervisor.step_verified"' in execution_source
    assert execution_source.index('"decision.made"') < execution_source.index(
        '"supervisor.step_verified"'
    )
    assert '"check.finished"' in finalization_source
    assert '"supervisor.verified"' in finalization_source


def test_runtime_path_resolution_logs_unexpected_resolver_failures() -> None:
    source = _read("app/core/agent/file_task_runtime.py")
    start = source.index("    def _resolve_task_file_path(")
    end = source.index("    def _plan_summary(", start)
    resolver = source[start:end]

    assert "except Exception as exc:" in resolver
    assert "[FileTaskRuntime] workspace path resolution skipped" in resolver
    assert "except Exception:\n            pass" not in resolver


def test_file_conversion_implementation_stays_outside_task_tools_registry() -> None:
    task_tools = _read("app/core/agent/task_tools.py")
    conversion = _read("app/core/agent/task_tools_conversion.py")

    assert "from app.core.agent.task_tools_conversion import (" in task_tools
    assert "def convert_docx_to_pdf_with_libreoffice(" in conversion
    assert "def convert_file(" in conversion
    assert "def list_conversions(" in conversion
    assert "return _conversion_convert_docx_to_pdf(" in task_tools
    assert "return _conversion_convert_file(" in task_tools
    assert "return _conversion_list_conversions(file_ext)" in task_tools


def test_workspace_task_runner_exports_only_cross_module_runtime_contract() -> None:
    source = _read("web/src/workspace/task-runner.ts")
    exported = source.split("export {", 1)[1].split("};", 1)[0]
    published = source.split("publishWorkspaceApi({", 1)[1].split("});", 1)[0]

    for module_name in (
        "streamTaskFlow",
        "restoreTaskRunCard",
        "resumePersistedFileTask",
    ):
        assert module_name in exported
    assert "restoreTaskRunCard" not in published
    assert "resumePersistedFileTask" not in published
    assert "publishWorkspaceApi({\n  streamTaskFlow" not in source

    for internal_name in (
        "compactTaskContract",
        "decodeTaskContract",
        "syncTaskInteractionSummary",
        "cancelFileTaskRun",
        "encodeTaskContract",
        "ensureTaskUiState",
        "syncTaskLiveProgress",
        "getEventHandlers",
        "parseSseEvents",
        "setTaskRunContext",
        "taskTerminalResult",
        "handleEvent_error",
        "TaskStatus",
    ):
        assert internal_name not in exported
        assert internal_name not in published

    assert "taskFlowTestHarness" in published
    assert "makeRunCard" in published
    assert "processEvent: processFileTaskStreamEvent" in published


def test_workspace_task_helpers_use_direct_module_owners_not_wa_bus() -> None:
    ai_review = _read("web/src/workspace/ai-review.ts")
    interactions = _read("web/src/workspace/task-card-interactions.ts")
    dispatcher = _read("web/src/workspace/task-dispatcher.ts")
    conversation = _read("web/src/workspace/conversation.ts")
    runtime_init = _read("web/src/workspace/runtime-init.ts")
    file_utils = _read("web/src/workspace/file-utils.ts")

    assert "import { compactTaskContract } from './task-contract-codec';" in ai_review
    assert "workspaceApi.compactTaskContract" not in ai_review
    assert "decodeTaskContract: (_value: string)" in interactions
    assert "api.decodeTaskContract" not in interactions
    assert "import { decodeTaskContract } from './task-contract-codec';" in dispatcher
    assert "(window as any).WA.decodeTaskContract" not in dispatcher
    for source in (conversation, runtime_init):
        assert "from './task-interaction-summary';" in source
        assert "workspaceApi.syncTaskInteractionSummary" not in source
    assert "import { streamTaskFlow } from './task-runner';" in runtime_init
    assert (
        "streamTaskFlow: (options: any) => workspaceApi.streamTaskFlow"
        not in runtime_init
    )
    assert "import { restoreTaskRunCard } from './task-runner';" in conversation
    assert "workspaceApi.restoreTaskRunCard" not in conversation
    for source in (ai_review, file_utils):
        assert "import { resumePersistedFileTask } from './task-runner';" in source
        assert "workspaceApi.resumePersistedFileTask" not in source


def test_workspace_task_browser_harness_is_e2e_gated_and_namespaced() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    browser = _read("tests/e2e/test_workspace_ai_assistant.py")

    assert "if ((window as any).__KOTO_E2E__ === true)" in runner
    assert "taskFlowTestHarness:" in runner
    assert "processEvent: processFileTaskStreamEvent" in runner
    assert "window.WA.streamTaskFlow" not in browser
    assert "window.WA.taskFlowTestHarness.streamTaskFlow" in browser
    assert 'page.add_init_script("window.__KOTO_E2E__ = true")' in browser
    assert "window.WA.makeRunCard" not in browser
    assert "window.WA.processFileTaskStreamEvent" not in browser
    assert "window.WA.taskFlowTestHarness.makeRunCard" in browser
    assert "window.WA.taskFlowTestHarness.processEvent" in browser


def test_generated_artifact_transactions_have_one_runtime_owner() -> None:
    recovery = _read("app/core/agent/file_task_financial_report_recovery.py")
    transaction = _read("app/core/agent/file_task_artifact_transaction.py")

    assert "from app.core.agent.file_task_artifact_transaction import (" in recovery
    assert "def run_scoped_staging_path(" in transaction
    assert "def commit_staged_artifact(" in transaction
    assert "def cleanup_run_owned_paths(" in transaction
    assert "def _staged_docx_path(" not in recovery
    assert "os.replace(" not in recovery
    assert len(recovery.splitlines()) <= 850
    assert len(transaction.splitlines()) <= 140
