from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_APP = ROOT / "web" / "app.py"
APP_BLUEPRINTS = ROOT / "web" / "app_blueprints.py"
KOTO_SPEC = ROOT / "koto.spec"
EDITOR_AI_BP = ROOT / "web" / "blueprints" / "editor_ai.py"
FILE_TASK_STREAM = ROOT / "web" / "file_task_stream.py"
MEMORY_RUNTIME = ROOT / "web" / "memory_runtime.py"
TASK_ORCHESTRATOR = ROOT / "web" / "task_orchestrator.py"
TASK_ORCHESTRATOR_RUNTIME = ROOT / "web" / "task_orchestrator_runtime.py"
TASK_ORCHESTRATOR_FILEGEN = ROOT / "web" / "task_orchestrator_filegen.py"
TASK_ORCHESTRATOR_STEPS = ROOT / "web" / "task_orchestrator_steps.py"
TASK_ORCHESTRATOR_PPT = ROOT / "web" / "task_orchestrator_ppt.py"
TASK_ORCHESTRATOR_SEARCH = ROOT / "web" / "task_orchestrator_search.py"
TASK_ORCHESTRATOR_QUALITY = ROOT / "web" / "task_orchestrator_quality.py"
CHAT_BP = ROOT / "web" / "blueprints" / "chat.py"
CHAT_FILE_HANDLERS = ROOT / "web" / "chat_file_handlers.py"
CHAT_STREAM_DIR = ROOT / "web" / "services" / "chat_stream"
SESSIONS_BP = ROOT / "web" / "blueprints" / "sessions.py"
PPT_API_ROUTES = ROOT / "web" / "ppt_api_routes.py"
SETTINGS_BP = ROOT / "web" / "blueprints" / "settings.py"
PAGES_BP = ROOT / "web" / "blueprints" / "pages.py"
AUTH_ROUTES = ROOT / "web" / "auth.py"
MEMORY_API_ROUTES = ROOT / "web" / "memory_api_routes.py"
ANALYTICS_BP = ROOT / "web" / "blueprints" / "analytics.py"
PROACTIVE_BP = ROOT / "web" / "blueprints" / "proactive.py"
EXECUTION_BP = ROOT / "web" / "blueprints" / "execution.py"
KNOWLEDGE_BP = ROOT / "web" / "blueprints" / "knowledge.py"
FILE_EDITOR_BP = ROOT / "web" / "blueprints" / "file_editor.py"
FILE_ORGANIZE_BP = ROOT / "web" / "blueprints" / "file_organize.py"
FILE_HUB_ROUTES = ROOT / "app" / "api" / "file_hub_routes.py"
TRAINING_DATA_BUILDER = ROOT / "app" / "core" / "learning" / "training_data_builder.py"
TRAINING_ROUTES = ROOT / "app" / "api" / "training_routes.py"
TEST_WEB_APP_COVERAGE = ROOT / "tests" / "unit" / "test_web_app_coverage.py"
TEST_WEB_APP_UTILS = ROOT / "tests" / "unit" / "test_web_app.py"

EXPECTED_WEB_APP_ROUTES: set[str] = set()
WEB_APP_LINE_BUDGET = 3525
TASK_ORCHESTRATOR_LINE_BUDGET = 230
ALLOWED_DIRECT_WEB_APP_IMPORTS: set[str] = set()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _app_route_paths() -> set[str]:
    tree = ast.parse(_read(WEB_APP), filename=str(WEB_APP))
    routes: set[str] = set()

    for node in ast.walk(tree):
        decorators = getattr(node, "decorator_list", ())
        for decorator in decorators:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "route"
                and isinstance(func.value, ast.Name)
                and func.value.id == "app"
            ):
                continue
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                routes.add(str(decorator.args[0].value))

    return routes


def test_web_app_keeps_legacy_route_surface_small():
    """All Flask routes should be registered through blueprints, not web/app.py."""
    assert _app_route_paths() == EXPECTED_WEB_APP_ROUTES


def test_training_api_routes_live_outside_training_data_builder():
    """TrainingDataBuilder should remain core logic; Flask routes belong in app.api."""
    builder_source = _read(TRAINING_DATA_BUILDER)
    routes_source = _read(TRAINING_ROUTES)
    app_blueprints = _read(APP_BLUEPRINTS)

    assert "@app.route" not in builder_source
    assert "register_training_routes" not in builder_source
    assert "training_bp = Blueprint" in routes_source
    assert "from app.api.training_routes import training_bp" in app_blueprints


def test_web_app_line_budget_does_not_regress():
    """The app module is still large; keep new work out while migration continues."""
    assert len(_read(WEB_APP).splitlines()) <= WEB_APP_LINE_BUDGET


def test_direct_web_app_imports_do_not_expand():
    """Runtime context is the migration bridge; new modules should not import web.app."""
    offenders: set[str] = set()
    for root in [ROOT / "web", ROOT / "app"]:
        for path in root.rglob("*.py"):
            source = _read(path)
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith(("from web.app import", "import web.app")):
                    rel_path = path.relative_to(ROOT).as_posix()
                    offenders.add(f"{rel_path}:{stripped}")

    assert offenders == ALLOWED_DIRECT_WEB_APP_IMPORTS


def test_migrated_app_class_tests_use_real_modules():
    """Tests for migrated classes should not keep old web.app compatibility imports alive."""
    source = _read(TEST_WEB_APP_COVERAGE) + "\n" + _read(TEST_WEB_APP_UTILS)
    forbidden_imports = [
        "from web.app import WebSearcher",
        "from web.app import ContextAnalyzer",
        "from web.app import Utils",
        "from web.app import SessionManager",
        "web.app.Utils",
        "web.app.ContextAnalyzer",
        "web.app.WebSearcher",
        "web.app.SessionManager",
        "from web.app import StreamInterruptManager",
        "from web.app import _safe_sse",
        "from web.app import _secure_filename",
        "from web.app import _normalize_proxy_url",
        "from web.app import _FakeGenerateContentResponse",
        "from web.app import _extract_prompt_text",
        "from web.app import _is_interactions_only",
        "from web.app import _get_DEFAULT_CHAT_SYSTEM_INSTRUCTION",
        "from web.app import _get_chat_system_instruction",
        "from web.app import _build_filegen_time_context",
        "from web.app import _parse_time_info_for_filegen",
    ]

    for forbidden in forbidden_imports:
        assert forbidden not in source


def test_chat_runtime_access_uses_named_context_helpers():
    """Chat modules should not add new stringly typed web.app runtime lookups."""
    paths = [CHAT_BP, CHAT_FILE_HANDLERS]
    paths.extend(CHAT_STREAM_DIR.rglob("*.py"))

    offenders = []
    for path in paths:
        source = _read(path)
        if "get_app_attr(" in source:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_web_app_does_not_reintroduce_editor_ai_handlers():
    """Editor AI routes belong in web.blueprints.editor_ai, not web/app.py."""
    source = _read(WEB_APP)
    retired_handlers = [
        "def editor_ai_task_stream(",
        "def editor_ai_task_stream_cancel(",
        "def editor_ai_stream(",
        "def editor_ai_chart(",
        "def editor_skill_list(",
        "def _build_editor_prompt(",
    ]

    for handler in retired_handlers:
        assert handler not in source


def test_blueprint_registry_is_the_primary_route_extension_point():
    source = _read(APP_BLUEPRINTS)

    assert "_WEB_BLUEPRINT_CONFIGS" in source
    assert "web.blueprints.workspace_assistant" in source
    assert "app.api.mcp_routes" in source
    assert "web.blueprints.editor_ai" in source
    assert "web.blueprints.voice" in source
    assert "register_memory_routes(app, get_memory_manager)" in source


def test_compat_route_registrars_use_blueprints_internally():
    """Compatibility registrars may remain, but business routes should be blueprint-owned."""
    auth_source = _read(AUTH_ROUTES)
    memory_source = _read(MEMORY_API_ROUTES)

    for source in [auth_source, memory_source]:
        assert "@app.route" not in source
        assert ".register_blueprint(" in source
        assert "Blueprint(" in source


def test_editor_ai_blueprint_uses_runtime_context_not_web_app_imports():
    source = _read(EDITOR_AI_BP)

    assert "from web.runtime_context import" in source
    assert "import web.app" not in source
    assert "from web.app import" not in source
    assert "get_app_attr(" not in source
    assert "_stream_file_task_request" not in source


def test_file_task_stream_lives_outside_web_app():
    """File task SSE orchestration belongs in web.file_task_stream, not web/app.py."""
    app_source = _read(WEB_APP)
    stream_source = _read(FILE_TASK_STREAM)

    assert "def stream_file_task_request(" in stream_source
    assert "def stream_file_task_chat_request(" in stream_source
    assert "stream_legacy_file_task" not in stream_source
    assert "stream_legacy_file_task" not in app_source
    assert "def _stream_file_task_request(" not in app_source
    assert "def _safe_file_task_event_dict(" not in app_source
    assert "def _file_task_event_to_safe_sse(" not in app_source
    assert "_FILE_TASK_CONTRACT" not in app_source


def test_ppt_api_handlers_stay_outside_web_app():
    """PPT session/download handlers belong to PPT blueprints and route modules."""
    app_source = _read(WEB_APP)
    ppt_source = _read(PPT_API_ROUTES)

    assert "def download_ppt():" not in app_source
    assert "def get_ppt_session(" not in app_source
    assert '@ppt_api_bp.route("/session/<session_id>", methods=["GET"])' in ppt_source
    assert '@ppt_api_bp.route("/download/<session_id>", methods=["GET"])' in ppt_source
    assert '"/api/ppt/download", methods=["POST"]' not in app_source


def test_debug_page_templates_stay_removed():
    pages_source = _read(PAGES_BP)

    assert "/test_upload" not in pages_source
    assert "test_upload.html" not in pages_source
    assert not (ROOT / "web" / "templates" / "test_upload.html").exists()
    assert not (ROOT / "web" / "templates" / "test_js.html").exists()


def test_orphan_file_operator_stays_removed_from_web_app():
    app_source = _read(WEB_APP)

    assert "class FileOperator" not in app_source
    assert "FOLDER_ORGANIZE_KEYWORDS" not in app_source
    assert "folder_auto_catalog" not in app_source


def test_web_searcher_implementation_stays_outside_web_app():
    app_source = _read(WEB_APP)
    web_searcher_source = _read(ROOT / "web" / "web_searcher.py")

    assert "class WebSearcher" not in app_source
    assert "from web.web_searcher import WebSearcher" in app_source
    assert "class WebSearcher" in web_searcher_source


def test_context_analyzer_implementation_stays_outside_web_app():
    app_source = _read(WEB_APP)
    context_analyzer_source = _read(ROOT / "web" / "context_analyzer.py")

    assert "class ContextAnalyzer" not in app_source
    assert "from web.context_analyzer import ContextAnalyzer" in app_source
    assert "class ContextAnalyzer" in context_analyzer_source


def test_utils_implementation_stays_outside_web_app():
    app_source = _read(WEB_APP)
    utils_source = _read(ROOT / "web" / "utils" / "assistant_utils.py")

    assert "class Utils" not in app_source
    assert "from web.utils.assistant_utils import Utils" in app_source
    assert "class Utils" in utils_source


def test_session_manager_implementation_stays_outside_web_app():
    app_source = _read(WEB_APP)
    session_manager_source = _read(ROOT / "web" / "session_manager.py")

    assert "class SessionManager" not in app_source
    assert "from web.session_manager import SessionManager" in app_source
    assert "class SessionManager" in session_manager_source


def test_local_dispatcher_implementation_stays_outside_web_app():
    app_source = _read(WEB_APP)
    local_dispatcher_source = _read(ROOT / "web" / "local_dispatcher.py")

    assert "class LocalDispatcher" not in app_source
    assert "from web.local_dispatcher import" in app_source
    assert "class LocalDispatcher" in local_dispatcher_source


def test_memory_api_registration_stays_outside_web_app():
    app_source = _read(WEB_APP)
    registry_source = _read(APP_BLUEPRINTS)

    assert "memory_api_routes" not in app_source
    assert "register_memory_routes(app, get_memory_manager)" in registry_source


def test_memory_runtime_implementation_stays_outside_web_app():
    app_source = _read(WEB_APP)
    memory_source = _read(MEMORY_RUNTIME)

    assert "def get_memory_manager(" not in app_source
    assert "def _start_memory_extraction(" not in app_source
    assert "def get_knowledge_base(" not in app_source
    assert "from web.memory_runtime import" in app_source
    assert "def get_memory_manager(" in memory_source
    assert "def _start_memory_extraction(" in memory_source
    assert "def get_knowledge_base(" in memory_source


def test_task_orchestrator_implementation_stays_outside_web_app():
    app_source = _read(WEB_APP)
    orchestrator_source = _read(TASK_ORCHESTRATOR)
    runtime_source = _read(TASK_ORCHESTRATOR_RUNTIME)

    assert "class TaskOrchestrator" not in app_source
    assert "from web.task_orchestrator import TaskOrchestrator" not in app_source
    assert "class TaskOrchestrator" in orchestrator_source
    assert "get_app_attr(" not in orchestrator_source
    assert "call_app_factory(" not in orchestrator_source
    assert "from web.task_orchestrator_runtime import" not in orchestrator_source
    assert "class ClientProxy" not in orchestrator_source
    assert "class SettingsManagerProxy" not in orchestrator_source
    assert "class ClientProxy" in runtime_source


def test_task_orchestrator_line_budget_does_not_regress():
    assert len(_read(TASK_ORCHESTRATOR).splitlines()) <= TASK_ORCHESTRATOR_LINE_BUDGET


def test_task_orchestrator_filegen_lives_outside_orchestrator_class():
    orchestrator_source = _read(TASK_ORCHESTRATOR)
    filegen_source = _read(TASK_ORCHESTRATOR_FILEGEN)

    assert (
        "from web.task_orchestrator_filegen import execute_file_gen"
        in orchestrator_source
    )
    assert "async def execute_file_gen(" in filegen_source
    assert "def _clean_filegen_text(" not in orchestrator_source
    assert "def _extract_markdown_table(" not in orchestrator_source
    assert "def _parse_ppt_outline(" not in orchestrator_source


def test_task_orchestrator_step_executors_live_outside_orchestrator_class():
    orchestrator_source = _read(TASK_ORCHESTRATOR)
    steps_source = _read(TASK_ORCHESTRATOR_STEPS)

    for name in ["painter", "research", "coder", "system"]:
        assert (
            f"from web.task_orchestrator_steps import execute_{name}"
            in orchestrator_source
        )
        assert f"async def execute_{name}(" in steps_source

    assert "client.models.generate_images(" not in orchestrator_source
    assert "WebSearcher.deep_research_for_ppt" not in orchestrator_source
    assert "call_interactions_api_sync" not in orchestrator_source
    assert "LocalExecutor.execute" not in orchestrator_source


def test_task_orchestrator_ppt_multi_step_lives_outside_orchestrator_class():
    orchestrator_source = _read(TASK_ORCHESTRATOR)
    ppt_source = _read(TASK_ORCHESTRATOR_PPT)

    assert (
        "from web.task_orchestrator_ppt import execute_ppt_multi_step"
        in orchestrator_source
    )
    assert "async def execute_ppt_multi_step(" in ppt_source
    assert "PPTContentPlanner" not in orchestrator_source
    assert "PPTGenerator" not in orchestrator_source
    assert "FileQualityGate.check_and_fix_ppt_outline" not in orchestrator_source
    assert "SmartFeedback" not in orchestrator_source


def test_task_orchestrator_web_search_lives_outside_orchestrator_class():
    orchestrator_source = _read(TASK_ORCHESTRATOR)
    search_source = _read(TASK_ORCHESTRATOR_SEARCH)

    assert (
        "from web.task_orchestrator_search import execute_web_search"
        in orchestrator_source
    )
    assert "async def execute_web_search(" in search_source
    assert "WebSearcher.search_with_grounding" not in orchestrator_source
    assert "await asyncio.sleep" not in orchestrator_source
    assert "from web.web_searcher import WebSearcher" not in orchestrator_source


def test_task_orchestrator_quality_scoring_lives_outside_orchestrator_class():
    orchestrator_source = _read(TASK_ORCHESTRATOR)
    quality_source = _read(TASK_ORCHESTRATOR_QUALITY)

    assert (
        "from web.task_orchestrator_quality import validate_quality"
        in orchestrator_source
    )
    assert "async def validate_quality(" in quality_source
    assert "client.models.generate_content" not in orchestrator_source
    assert "GenerateContentConfig" not in orchestrator_source
    assert "gemini-2.5-flash-lite" not in orchestrator_source


def test_removed_file_hub_open_endpoint_is_explicitly_named():
    source = _read(FILE_HUB_ROUTES)

    assert 'file_hub_bp.route("/open", methods=["POST"])' in source
    assert "def removed_native_open_file(" in source
    assert "def retired_open_file(" not in source


def test_chat_session_and_settings_blueprints_use_runtime_context():
    for path in [CHAT_BP, SESSIONS_BP, SETTINGS_BP]:
        source = _read(path)
        assert "from web.runtime_context import" in source
        assert "import web.app" not in source
        assert "from web.app import" not in source


def test_session_and_settings_runtime_access_uses_named_helpers():
    for path in [SESSIONS_BP, SETTINGS_BP]:
        source = _read(path)
        assert "get_app_attr(" not in source


def test_service_blueprints_use_named_runtime_helpers():
    for path in [
        ANALYTICS_BP,
        PROACTIVE_BP,
        EXECUTION_BP,
        KNOWLEDGE_BP,
        FILE_EDITOR_BP,
        FILE_ORGANIZE_BP,
    ]:
        source = _read(path)
        assert "from web.runtime_context import" in source
        assert "call_app_factory(" not in source
        assert "get_app_attr(" not in source


def test_runtime_factory_bridge_has_no_production_callers():
    offenders = []
    for root in [ROOT / "web", ROOT / "app"]:
        for path in root.rglob("*.py"):
            if path == ROOT / "web" / "runtime_context.py":
                continue
            source = _read(path)
            if "call_app_factory(" in source:
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_runtime_string_attr_bridge_has_no_production_callers():
    offenders = []
    for root in [ROOT / "web", ROOT / "app"]:
        for path in root.rglob("*.py"):
            if path == ROOT / "web" / "runtime_context.py":
                continue
            source = _read(path)
            if "get_app_attr(" in source:
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_legacy_process_launch_switch_routes_stay_removed():
    settings_source = _read(SETTINGS_BP)

    assert '"/api/switch-to-mini"' not in settings_source
    assert '"/api/switch-to-main"' not in settings_source
    assert "def switch_to_mini(" not in settings_source
    assert "def switch_to_main(" not in settings_source
    assert '"/api/window/switch-to-mini"' in settings_source


def test_packaging_does_not_reintroduce_removed_shims():
    spec = _read(KOTO_SPEC)

    assert "web.voice_api_enhanced" not in spec
    assert "web.settings_backup" not in spec
    assert not (ROOT / "web" / "voice_api_enhanced.py").exists()
    assert not (ROOT / "web" / "settings_backup.py").exists()


def test_legacy_microphone_voice_stack_stays_removed():
    spec = _read(KOTO_SPEC)
    removed_files = [
        "voice_" + "engine.py",
        "voice_" + "fast.py",
        "voice_" + "input.py",
        "voice_" + "interaction.py",
        "voice_" + "recognition_enhanced.py",
        "speech_" + "transcriber.py",
    ]

    for filename in removed_files:
        assert not (ROOT / "web" / filename).exists()

    retired_terms = [
        "web.voice_" + "engine",
        "web.voice_" + "fast",
        "web.voice_" + "input",
        "py" + "audio",
        "vo" + "sk",
        "sound" + "device",
        "sound" + "file",
        "com" + "types",
        "sapi" + "svr",
        "SAPI",
        "Sp" + "Voice",
        "System." + "Speech",
        "speech_" + "recognition",
    ]
    for term in retired_terms:
        assert term not in spec


def test_selenium_browser_automation_stays_removed():
    workspace_source = _read(ROOT / "web" / "blueprints" / "workspace.py")
    spec_source = _read(ROOT / "koto.spec")

    assert not (ROOT / "web" / "browser_automation.py").exists()
    assert "/api/browser/" not in workspace_source
    assert "get_browser_automation" not in workspace_source
    assert "selenium" not in workspace_source.lower()
    assert "webdriver" not in workspace_source.lower()
    assert "browser_automation" not in spec_source


def test_retired_browser_and_system_voice_terms_stay_out_of_production_code():
    production_roots = [ROOT / "web", ROOT / "app", ROOT / "src"]
    config_files = [
        ROOT / "config" / "requirements.txt",
        ROOT / "config" / "requirements.lock",
        ROOT / "koto.spec",
    ]
    retired_terms = [
        "browser_" + "automation",
        "get_browser_" + "automation",
        "selen" + "ium",
        "web" + "driver",
        "sapi" + "svr",
        "SA" + "PI",
        "Sp" + "Voice",
        "System." + "Speech",
        "speech_" + "recognition",
        "voice_" + "recognition",
        "get_voice_" + "recognizer",
        "vo" + "sk",
        "sound" + "device",
        "sound" + "file",
        "com" + "types",
    ]
    offenders = []
    for root in production_roots:
        for path in root.rglob("*.py"):
            source = _read(path)
            for term in retired_terms:
                if term in source:
                    offenders.append(f"{path.relative_to(ROOT)}: {term}")
    for path in config_files:
        source = _read(path)
        for term in retired_terms:
            if term in source:
                offenders.append(f"{path.relative_to(ROOT)}: {term}")

    assert not (ROOT / "config" / "requirements_voice.txt").exists()

    assert offenders == []


def test_retired_external_planner_config_stays_removed():
    followups = _read(ROOT / "config" / "file_task_followups.json").lower()

    assert "hermes" not in followups
    assert "prefer_hermes" not in followups
