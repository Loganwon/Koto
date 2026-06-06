from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_workspace_file_assistant_uses_single_whitebox_task_stream_by_default():
    assistant_js = _read("web/static/js/workspace-assistant.js")
    dispatcher_js = _read("web/static/js/workspace-task-dispatcher.js")
    task_js = _read("web/static/js/workspace-ai-task.js")
    quick_actions_js = _read("web/static/js/workspace-ai-quick-actions.js")

    assert "window.WA.createTaskDispatcher" in dispatcher_js
    assert "_waTaskDispatcher.dispatchMessage" in assistant_js
    assert "_waTaskDispatcher.dispatchQuickAction" in assistant_js
    assert "window.WA.streamWhiteboxTask" in task_js
    assert "fetch('/api/editor/ai/task-stream'" in task_js
    assert "fetch('/api/editor/ai/task-stream'" not in assistant_js
    assert "legacyEditorFallback: true" not in quick_actions_js
    assert "legacyEditorFallback" not in quick_actions_js


def test_workspace_static_js_only_task_renderer_calls_file_task_stream():
    static_js_dir = _repo_root() / "web" / "static" / "js"
    offenders = []
    for path in static_js_dir.glob("*.js"):
        source = path.read_text(encoding="utf-8")
        if "/api/editor/ai/task-stream" in source and path.name != "workspace-ai-task.js":
            offenders.append(path.name)

    assert offenders == []


def test_workspace_file_assistant_never_calls_retired_ai_task_routes():
    checked_paths = [
        "web/static/js/workspace-assistant.js",
        "web/static/js/workspace-task-dispatcher.js",
        "web/static/js/workspace-ai-quick-actions.js",
        "web/static/js/workspace-ai-task.js",
    ]
    retired_routes = [
        "/api/editor/ai/stream",
        "/api/editor/ai/chart",
        "/api/editor/ai/task-execute",
        "/api/editor/ai/skill-execute",
        "/api/v1/workspace/quick-action",
    ]

    for rel_path in checked_paths:
        source = _read(rel_path)
        for route in retired_routes:
            assert route not in source


def test_editor_ai_blueprint_exposes_single_file_task_endpoint():
    source = _read("web/blueprints/editor_ai.py")

    assert '@editor_ai_bp.route("/api/editor/ai/task-stream", methods=["POST"])' in source
    assert '@editor_ai_bp.route("/api/editor/ai/task-stream/cancel", methods=["POST"])' in source
    assert "/api/editor/ai/task-execute" not in source
    assert "/api/editor/ai/skill-execute" not in source
    assert "stream_file_task_request(data)" in source


def test_workspace_task_payload_does_not_attach_current_open_file_implicitly():
    dispatcher_js = _read("web/static/js/workspace-task-dispatcher.js")
    assistant_js = _read("web/static/js/workspace-assistant.js")

    assert "currentFile: null," in dispatcher_js
    assert "files.push(currentFile)" not in dispatcher_js
    assert "current_file: currentFile" not in dispatcher_js
    assert "getCurrentAIContextPath" not in dispatcher_js
    assert "_ensureCurrentFileAttachedForQuickAction" not in assistant_js


def test_workspace_assistant_does_not_open_files_with_os_native_apps():
    assistant_js = _read("web/static/js/workspace-assistant.js")
    workspace_bp = _read("web/blueprints/workspace_assistant.py")

    assert ("/api/v1/workspace/open-" + "native") not in assistant_js
    assert ("/api/v1/workspace/open-" + "native") not in workspace_bp
    assert ("os." + "startfile") not in workspace_bp
    assert ("xdg-" + "open") not in workspace_bp


def test_global_file_search_native_open_routes_stay_removed():
    app_js = _read("web/static/js/app.js")
    file_editor_bp = _read("web/blueprints/file_editor.py")
    file_scanner = _read("web/file_scanner.py")
    app_py = _read("web/app.py")

    assert ("/api/scan/" + "open") not in app_js
    assert ("/api/scan/" + "open") not in file_editor_bp
    assert "def scan_open" not in file_editor_bp
    assert "def open_file(cls, path" not in file_scanner
    assert "FileScanner.open_file" not in app_py


def test_file_network_native_open_route_stays_removed():
    misc_api_bp = _read("web/blueprints/misc_api.py")
    file_network = _read("web/processed_file_network.py")
    file_network_html = _read("web/templates/file_network.html")

    assert ("/api/file-network/" + "open") not in misc_api_bp
    assert "def file_network_open" not in misc_api_bp
    assert "def open_file(self, file_id" not in file_network
    assert ("/api/file-network/" + "open") not in file_network_html
    assert "copyFilePath" in file_network_html


def test_productivity_plugin_does_not_expose_native_open_tool():
    plugin = _read("app/core/agent/plugins/productivity_plugin.py")
    tool_router = _read("app/core/routing/tool_router.py")

    assert "open_file_or_folder" not in plugin
    assert "open_file_or_folder" not in tool_router
    assert ("os." + "startfile") not in plugin
    assert ("xdg-" + "open") not in plugin


def test_productivity_plugin_does_not_expose_file_or_email_side_effect_tools():
    plugin = _read("app/core/agent/plugins/productivity_plugin.py")
    tool_router = _read("app/core/routing/tool_router.py")

    retired_tools = {
        "send_email",
        "move_file",
        "delete_file",
        "zip_files",
        "unzip_file",
    }
    for tool_name in retired_tools:
        assert tool_name not in plugin
        assert tool_name not in tool_router


def test_standalone_email_client_routes_stay_removed():
    misc_api_bp = _read("web/blueprints/misc_api.py")

    assert not (_repo_root() / "web/email_manager.py").exists()
    assert "/api/email/" not in misc_api_bp
    assert "get_email_manager" not in misc_api_bp


def test_alerting_plugin_stays_local_log_only():
    alerting_plugin = _read("app/core/agent/plugins/alerting_plugin.py")
    alert_manager = _read("app/core/monitoring/alert_manager.py")

    for removed in (
        "configure_email_alerts",
        "add_webhook_alert",
        "AlertChannel.EMAIL",
        "AlertChannel.WEBHOOK",
        "smtplib",
        "requests.post",
        "_send_email",
        "_send_webhook",
    ):
        assert removed not in alerting_plugin
        assert removed not in alert_manager


def test_network_plugin_stays_read_only():
    network_plugin = _read("app/core/agent/plugins/network_plugin.py")

    assert "http_post" not in network_plugin
    assert "requests.post" not in network_plugin


def test_system_fix_script_generation_stays_removed():
    factory = _read("app/core/agent/factory.py")
    agent_routes = _read("app/api/agent_routes.py")

    assert not (_repo_root() / "app/core/agent/plugins/script_generation_plugin.py").exists()
    assert not (_repo_root() / "app/core/scripts/script_generator.py").exists()
    assert "ScriptGenerationPlugin" not in factory
    assert "/generate-script" not in agent_routes
    for dangerous_text in (
        "Stop-Process",
        "Remove-Item",
        "systemctl restart",
        "generate_fix_script",
    ):
        assert dangerous_text not in factory
        assert dangerous_text not in agent_routes


def test_local_executor_no_longer_performs_system_side_effects():
    local_executor = _read("web/local_executor.py")

    assert "APP_ALIASES" not in local_executor
    assert "SYSTEM_KEYWORDS" not in local_executor
    assert "def extract_app_name" not in local_executor
    assert "def find_app_in_start_menu" not in local_executor
    assert "def find_app_smart" not in local_executor
    assert "def open_file_or_directory" not in local_executor
    assert "def send_keystroke" not in local_executor
    assert ("os." + "startfile") not in local_executor
    assert "shutdown /" not in local_executor
    assert "snippingtool" not in local_executor
    assert "webbrowser.open" not in local_executor
    assert "keyboard.hotkey" not in local_executor


def test_agent_tool_router_does_not_offer_system_side_effect_tools():
    plugin = _read("app/core/agent/plugins/productivity_plugin.py")
    sandbox_plugin = _read("app/core/agent/plugins/sandbox_plugin.py")
    system_tools_plugin = _read("app/core/agent/plugins/system_tools_plugin.py")
    tool_router = _read("app/core/routing/tool_router.py")

    assert "shell_command" not in plugin
    assert "take_screenshot" not in plugin
    assert "run_shell_command" not in sandbox_plugin
    assert "pip_install" not in system_tools_plugin
    assert "open_application" not in tool_router
    assert "take_screenshot" not in tool_router
    assert "shell_command" not in tool_router


def test_routing_layer_does_not_fast_track_app_control_as_system():
    rule_router = _read("app/core/routing/rule_router.py")
    smart_dispatcher = _read("app/core/routing/smart_dispatcher.py")
    ai_router = _read("app/core/routing/ai_router.py")

    assert "_sys_starters" not in rule_router
    assert "_sys_action_starters" not in smart_dispatcher
    assert "_fb_sys_starters" not in smart_dispatcher
    assert "Action-Direct" not in smart_dispatcher
    assert "Fallback-ActionVerb" not in smart_dispatcher
    assert "打开微信/Chrome/某应用" not in ai_router


def test_workspace_file_tree_drag_to_ai_stays_readonly_attachment_flow():
    assistant_js = _read("web/static/js/workspace-assistant.js")

    assert 'draggable="true"' in assistant_js
    assert "application/wa-file-path" in assistant_js
    assert "_getAIAttachmentDropPayload" in assistant_js
    assert "_addFileToAIContext(payload.filePath)" in assistant_js


def test_workspace_file_browser_folder_actions_are_available():
    assistant_js = _read("web/static/js/workspace-assistant.js")
    workspace_bp = _read("web/blueprints/workspace_assistant.py")

    assert "_dropOntoFolder" in assistant_js
    assert ("fs_" + "copy") in assistant_js
    assert ("upload-" + "to-folder") in assistant_js
    assert "def fs_create_file" in workspace_bp
    assert "def fs_create_folder" in workspace_bp
    assert "def fs_rename" in workspace_bp
    assert "def fs_copy" in workspace_bp
    assert "def fs_delete" in workspace_bp
    assert "def upload_to_folder" in workspace_bp
    assert "open-native" not in workspace_bp


def test_workspace_task_card_renderer_guards_non_dom_cards():
    task_js = _read("web/static/js/workspace-ai-task.js")

    assert "function isTaskCardElement(value)" in task_js
    assert "typeof value.querySelectorAll === 'function'" in task_js
    assert "if (!isTaskCardElement(card)) return;" in task_js
    assert "function applyUiState(card, uiState)" in task_js
    assert "if (!isTaskCardElement(card) || !uiState || typeof uiState !== 'object') return;" in task_js
    assert "function applyTerminalPayload(card, evt, payload, options)" in task_js


def test_workspace_task_progress_has_live_plan_linked_feedback():
    task_js = _read("web/static/js/workspace-ai-task.js")
    workspace_css = _read("web/static/css/workspace.css")
    workspace_template = _read("web/templates/workspace_assistant.html")
    index_template = _read("web/templates/index.html")

    assert 'id="wa-task-live-progress"' in workspace_template
    assert 'id="wa-task-live-progress"' in index_template
    assert "function syncTaskLiveProgress(card)" in task_js
    assert "function taskPlanProgress(card)" in task_js
    assert "state.plannedStepCount = steps.length;" in task_js
    assert "state.progressExplicit = hasExplicitProgress || !!uiState.terminal;" in task_js
    assert "basis = explicit ? 'explicit' : (plan.total ? 'planned' : 'estimated')" in task_js
    assert "valueText = `按计划 ${plan.completed}/${plan.total}`;" in task_js
    assert "syncTaskLiveProgress(card);" in task_js
    assert ".wa-task-live-progress" in workspace_css
    assert '.wa-task-progress[data-basis="planned"]' in workspace_css
    assert '.wa-task-progress[data-basis="estimated"]' in workspace_css


def test_workspace_stepwise_resume_payload_does_not_increment_explicit_step_index():
    dispatcher_js = _read("web/static/js/workspace-task-dispatcher.js")

    assert "const hasExplicitStepIndex = Object.prototype.hasOwnProperty.call(existingBatchControl, 'step_index')" in dispatcher_js
    assert "const resumeStepIndex = hasExplicitStepIndex ? currentStep : currentStep + 1;" in dispatcher_js
    assert "step_index: resumeStepIndex" in dispatcher_js
    assert "next_step_index: resumeStepIndex" in dispatcher_js
