from __future__ import annotations

import ast
import re
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
TASK_ORCHESTRATOR_RESULTS = ROOT / "web" / "task_orchestrator_results.py"
WEB_SERVICE_MIGRATION_CANDIDATES = ROOT / "docs" / "WEB_SERVICE_MIGRATION_CANDIDATES.md"
WORKFLOW_API_BP = ROOT / "web" / "blueprints" / "workflow_api.py"
WORKFLOW_CATALOG = ROOT / "app" / "core" / "workflows" / "catalog.py"
WORKFLOW_EXECUTION = ROOT / "app" / "core" / "workflows" / "execution.py"
WORKFLOW_EXECUTOR_REGISTRY = ROOT / "app" / "core" / "workflows" / "registry.py"
WORKFLOW_FILE_STORE = ROOT / "app" / "core" / "workflows" / "file_store.py"
WORKFLOW_SKILL_MAPPING = ROOT / "app" / "core" / "workflows" / "skill_mapping.py"
PPT_WORKFLOW_SKILL_MATRIX = ROOT / "docs" / "PPT_WORKFLOW_SKILL_ROUTE_MATRIX.md"
PPT_PLUGIN = ROOT / "app" / "core" / "agent" / "plugins" / "ppt_plugin.py"
PPT_GENERATION_SERVICE = (
    ROOT / "app" / "core" / "services" / "ppt_generation_service.py"
)
PPT_GENERATION_CONTRACT = (
    ROOT / "app" / "core" / "services" / "ppt_generation_contract.py"
)
TEMPLATE_LIBRARY = ROOT / "web" / "template_library.py"
PPT_API_ROUTES = ROOT / "web" / "ppt_api_routes.py"
PPT_GENERATOR = ROOT / "web" / "ppt_generator.py"
CHAT_BP = ROOT / "web" / "blueprints" / "chat.py"
CHAT_FILE_HANDLERS = ROOT / "web" / "chat_file_handlers.py"
CHAT_STREAM_DIR = ROOT / "web" / "services" / "chat_stream"
CHAT_REGULAR_HANDLER = (
    ROOT / "web" / "services" / "chat_stream" / "generate" / "regular_handler.py"
)
CHAT_GENERATION_POLICY = ROOT / "app" / "core" / "llm" / "chat_generation_policy.py"
SESSIONS_BP = ROOT / "web" / "blueprints" / "sessions.py"
SETTINGS_BP = ROOT / "web" / "blueprints" / "settings.py"
PAGES_BP = ROOT / "web" / "blueprints" / "pages.py"
AUTH_ROUTES = ROOT / "web" / "blueprints" / "auth.py"
MEMORY_API_ROUTES = ROOT / "web" / "blueprints" / "memory_api.py"
ANALYTICS_BP = ROOT / "web" / "blueprints" / "analytics.py"
PROACTIVE_BP = ROOT / "web" / "blueprints" / "proactive.py"
EXECUTION_BP = ROOT / "web" / "blueprints" / "execution.py"
KNOWLEDGE_BP = ROOT / "web" / "blueprints" / "knowledge.py"
FILE_EDITOR_BP = ROOT / "web" / "blueprints" / "file_editor.py"
FILE_ORGANIZE_BP = ROOT / "web" / "blueprints" / "file_organize.py"
FILE_HUB_ROUTES = ROOT / "app" / "api" / "file_hub_routes.py"
TASK_ROUTES = ROOT / "app" / "api" / "task_routes.py"
TRAINING_DATA_BUILDER = ROOT / "app" / "core" / "learning" / "training_data_builder.py"
TRAINING_ROUTES = ROOT / "app" / "api" / "training_routes.py"
TEST_WEB_APP_COVERAGE = ROOT / "tests" / "unit" / "test_web_app_coverage.py"
TEST_WEB_APP_UTILS = ROOT / "tests" / "unit" / "test_web_app.py"

EXPECTED_WEB_APP_ROUTES: set[str] = set()
WEB_APP_LINE_BUDGET = 1800
TASK_ORCHESTRATOR_LINE_BUDGET = 199
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


def test_proxy_candidate_discovery_is_extracted_from_app_wiring():
    app_source = _read(WEB_APP)
    proxy_source = _read(ROOT / "web" / "app_proxy.py")

    assert (
        "from web.app_proxy import configure_proxy, extract_system_proxy_candidates"
        in app_source
    )
    assert "configure_proxy(" in app_source
    assert "return extract_system_proxy_candidates(" in app_source
    assert "def extract_system_proxy_candidates(" in proxy_source
    assert "def configure_proxy(" in proxy_source
    assert "Internet Settings" in proxy_source


def test_web_app_uses_core_koto_brain_compatibility_alias():
    """Chat orchestration belongs to the core; web.app keeps the legacy name."""
    source = _read(WEB_APP)

    assert "from app.core.brain import KotoBrain" in source
    assert "class KotoBrain:" not in source


def test_koto_brain_uses_explicit_runtime_services_not_web_runtime_context():
    brain_source = _read(ROOT / "app" / "core" / "brain.py")
    app_source = _read(WEB_APP)

    assert "class BrainRuntimeServices" in brain_source
    assert "web.runtime_context" not in brain_source
    assert "configure_default_brain_runtime(" in app_source
    assert "BrainRuntimeServices(" in app_source


def test_background_file_tasks_call_the_file_task_stream_owner_directly():
    """The task API must not route file work through the web.app compatibility bridge."""
    source = _read(TASK_ROUTES)

    assert "from web.file_task_stream import stream_file_task_request" in source
    assert "from web.runtime_context import stream_file_task_request" not in source


def test_core_llm_provider_helpers_do_not_reflect_through_web_runtime_context():
    source = _read(ROOT / "app" / "core" / "agent" / "llm_provider_helpers.py")

    assert (
        "from app.core.llm.model_selection import get_configured_cloud_model" in source
    )
    assert "web.runtime_context" not in source


def test_memory_tools_plugin_uses_the_application_context_owner_directly():
    source = _read(
        ROOT / "app" / "core" / "agent" / "plugins" / "memory_tools_plugin.py"
    )

    assert "from app.core.app_context import ctx" in source
    assert "web.memory_runtime" not in source
    assert "EnhancedMemoryManager()" not in source


def test_system_info_service_is_core_owned_without_web_compatibility_alias():
    performance_plugin = _read(
        ROOT
        / "app"
        / "core"
        / "agent"
        / "plugins"
        / "performance_analysis_plugin.py"
    )
    system_info_plugin = _read(
        ROOT / "app" / "core" / "agent" / "plugins" / "system_info_plugin.py"
    )
    core_service = _read(ROOT / "app" / "core" / "services" / "system_info.py")
    context_injector = _read(ROOT / "web" / "context_injector.py")
    system_instruction = _read(ROOT / "web" / "chat_system_instruction.py")

    expected_import = (
        "from app.core.services.system_info import get_system_info_collector"
    )
    assert expected_import in performance_plugin
    assert expected_import in system_info_plugin
    assert "from web.system_info import" not in performance_plugin
    assert "from web.system_info import" not in system_info_plugin
    assert "class SystemInfoCollector:" in core_service
    assert expected_import in context_injector
    assert "from app.core.services.system_info import (" in system_instruction
    assert not (ROOT / "web" / "system_info.py").exists()


def test_ppt_image_management_is_core_owned():
    pipeline_source = _read(ROOT / "app" / "core" / "services" / "ppt_pipeline.py")
    core_image_manager = _read(
        ROOT / "app" / "core" / "services" / "image_manager.py"
    )

    assert "from app.core.services.image_manager import ImageManager" in pipeline_source
    assert "web.runtime_context" not in pipeline_source
    assert "from web.image_manager import" not in pipeline_source
    assert "class ImageManager:" in core_image_manager
    assert "from web.web_searcher import" not in core_image_manager
    assert not (ROOT / "web" / "image_manager.py").exists()


def test_settings_manager_is_core_owned_without_web_import_alias():
    model_selection = _read(ROOT / "app" / "core" / "llm" / "model_selection.py")
    server = _read(ROOT / "src" / "server.py")
    diagnostics = _read(ROOT / "src" / "startup_diagnostics.py")
    spec = _read(ROOT / "koto.spec")

    expected_import = "from app.core.config.user_settings import SettingsManager"
    assert expected_import in model_selection
    assert expected_import in server
    assert '"app.core.config.user_settings",' in diagnostics
    assert "'web.settings'" not in spec
    assert not (ROOT / "web" / "settings.py").exists()


def test_web_configuration_helpers_have_one_shared_owner():
    app_source = _read(ROOT / "web" / "app.py")
    settings_route = _read(ROOT / "web" / "blueprints" / "settings.py")
    file_services = _read(ROOT / "web" / "lazy_loaders" / "file_services.py")
    runtime_services = _read(ROOT / "web" / "runtime_services.py")

    assert "from web.shared import (" in app_source
    assert "from web.shared import invalidate_settings_cache" in settings_route
    assert "from web.shared import get_organize_root" in file_services
    assert "from web.shared import get_organize_root as _get_service" in runtime_services
    assert not (ROOT / "web" / "config" / "__init__.py").exists()


def test_web_app_keeps_executable_lifecycle_outside_application_factory():
    """Importing the Flask module must not also own process lifecycle code."""
    source = _read(WEB_APP)

    assert "from web.app_entrypoint import run_web_server" in source
    assert "def start_background_services" not in source


def test_direct_web_app_imports_do_not_expand():
    """Runtime context is the migration bridge; new modules should not import web.app."""
    offenders: set[str] = set()
    package_import_pattern = re.compile(
        r"from\s+web\s+import\s+app(?:\s+as\s+\w+|\s*,|$)"
    )
    for root in [ROOT / "web", ROOT / "app"]:
        for path in root.rglob("*.py"):
            source = _read(path)
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith(
                    ("from web.app import", "import web.app")
                ) or package_import_pattern.match(stripped):
                    rel_path = path.relative_to(ROOT).as_posix()
                    offenders.add(f"{rel_path}:{stripped}")

    assert offenders == ALLOWED_DIRECT_WEB_APP_IMPORTS


def test_production_code_uses_runtime_context_instead_of_sys_modules_web_app():
    """Only runtime_context may inspect sys.modules for the transitional app module."""

    def _touches_web_app_sys_modules(path: Path) -> bool:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript):
                value = node.value
                if (
                    isinstance(value, ast.Attribute)
                    and value.attr == "modules"
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "sys"
                    and isinstance(node.slice, ast.Constant)
                    and node.slice.value == "web.app"
                ):
                    return True
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "get"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "modules"
                    and isinstance(func.value.value, ast.Name)
                    and func.value.value.id == "sys"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "web.app"
                ):
                    return True
            if isinstance(node, ast.Compare):
                if (
                    isinstance(node.left, ast.Constant)
                    and node.left.value == "web.app"
                    and any(isinstance(op, ast.In) for op in node.ops)
                ):
                    for comparator in node.comparators:
                        if (
                            isinstance(comparator, ast.Attribute)
                            and comparator.attr == "modules"
                            and isinstance(comparator.value, ast.Name)
                            and comparator.value.id == "sys"
                        ):
                            return True
        return False

    offenders = []
    for root in [ROOT / "web", ROOT / "app"]:
        for path in root.rglob("*.py"):
            if path == ROOT / "web" / "runtime_context.py":
                continue
            if _touches_web_app_sys_modules(path):
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


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


def test_regular_chat_generation_policy_lives_in_core_llm():
    handler_source = _read(CHAT_REGULAR_HANDLER)
    policy_source = _read(CHAT_GENERATION_POLICY)

    assert "from app.core.llm.chat_generation_policy import" in handler_source
    assert "select_regular_model(task_type, MODEL_MAP)" in handler_source
    assert "should_try_local_chat_fast_path(" in handler_source
    assert "first_token_timeout_seconds(task_type)" in handler_source
    assert "def select_regular_model(" in policy_source
    assert "def should_try_local_chat_fast_path(" in policy_source
    assert "def first_token_timeout_seconds(" in policy_source


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
    assert (
        "from web.file_task_stream import safe_editor_sse, stream_file_task_request"
        in source
    )
    assert "from web.editor_ai_text import clean_selection_text" in source
    runtime_source = _read(ROOT / "web" / "runtime_context.py")
    assert "def stream_file_task_request(" not in runtime_source
    assert "def safe_editor_sse(" not in runtime_source
    stream_source = _read(FILE_TASK_STREAM)
    assert (
        "from web.blueprints.editor_ai import _clean_selection_text"
        not in stream_source
    )


def test_file_task_stream_lives_outside_web_app():
    """File task SSE orchestration belongs in web.file_task_stream, not web/app.py."""
    app_source = _read(WEB_APP)
    stream_source = _read(FILE_TASK_STREAM)

    assert "def stream_file_task_request(" in stream_source
    assert "def stream_file_task_chat_request(" not in stream_source
    assert "stream_file_task_chat_request" not in app_source
    assert 'payload.get("completed_task", True)' not in stream_source
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
    assert (
        "from app.core.services.ppt_generation_service import PPTGenerationService"
        in ppt_source
    )
    assert "PPTGenerationService().render_editor_pptx(" in ppt_source
    assert "from app.core.services.ppt_generator import" not in ppt_source
    assert '"/api/ppt/download", methods=["POST"]' not in app_source


def test_debug_page_templates_stay_removed():
    pages_source = _read(PAGES_BP)

    assert "/test_upload" not in pages_source
    assert "test_upload.html" not in pages_source
    assert not (ROOT / "web" / "templates" / "test_upload.html").exists()
    assert not (ROOT / "web" / "templates" / "test_js.html").exists()


def test_orphan_file_operator_stays_removed_from_web_app():
    app_source = _read(WEB_APP)

    assert not (ROOT / "web" / "file_operator.py").exists()
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


def test_local_dispatcher_removed_from_web():
    """LocalDispatcher was unused dead code and has been removed."""
    local_dispatcher_path = ROOT / "web" / "local_dispatcher.py"
    assert (
        not local_dispatcher_path.exists()
    ), "web/local_dispatcher.py should not exist (dead code, removed)"


def test_memory_api_registration_stays_outside_web_app():
    app_source = _read(WEB_APP)
    registry_source = _read(APP_BLUEPRINTS)

    assert "memory_api_routes" not in app_source
    assert "register_memory_routes(app, get_memory_manager)" in registry_source
    assert 'logger.info("[Memory] ✅ 记忆 API 已注册")' in registry_source
    assert 'logger.info("[Parallel] ✅ 并行任务 API 已注册")' in registry_source
    assert "[MemoryAPI]" not in registry_source


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
    assert "from web.memory_manager import MemoryManager" not in memory_source
    assert (
        "from enhanced_memory_manager import EnhancedMemoryManager" not in memory_source
    )


def test_regular_chat_uses_the_canonical_memory_runtime():
    source = _read(
        ROOT / "web" / "services" / "chat_stream" / "generate" / "regular_handler.py"
    )

    assert (
        "from web.memory_runtime import _start_memory_extraction, get_memory_manager"
        in source
    )
    assert "def _start_memory_extraction(*args, **kwargs):" not in source
    assert "class _CompatMemoryManager" not in source


def test_editor_ai_removes_unconsumed_legacy_routes():
    source = _read(ROOT / "web" / "blueprints" / "editor_ai.py")

    assert 'route("/api/editor/ai/task-stream", methods=["POST"])' in source
    assert 'route("/api/editor/ai/agent", methods=["POST"])' not in source
    assert 'route("/api/editor/ai/chart-rerun", methods=["POST"])' not in source
    assert "def _agent_step_events(" not in source


def test_task_orchestrator_implementation_stays_outside_web_app():
    app_source = _read(WEB_APP)
    orchestrator_source = _read(TASK_ORCHESTRATOR)
    runtime_source = _read(TASK_ORCHESTRATOR_RUNTIME)
    results_source = _read(TASK_ORCHESTRATOR_RESULTS)

    assert "class TaskOrchestrator" not in app_source
    assert "from web.task_orchestrator import TaskOrchestrator" not in app_source
    assert "class TaskOrchestrator" in orchestrator_source
    assert "get_app_attr(" not in orchestrator_source
    assert "call_app_factory(" not in orchestrator_source
    assert "from web.task_orchestrator_runtime import" not in orchestrator_source
    assert "class ClientProxy" not in orchestrator_source
    assert "class SettingsManagerProxy" not in orchestrator_source
    assert "class ClientProxy" in runtime_source
    assert "def merge_task_results(" in results_source


def test_task_orchestrator_result_merge_is_pure_helper():
    orchestrator_source = _read(TASK_ORCHESTRATOR)
    results_source = _read(TASK_ORCHESTRATOR_RESULTS)

    assert (
        "from web.task_orchestrator_results import merge_task_results"
        in orchestrator_source
    )
    assert "return merge_task_results(subtasks, context)" in orchestrator_source
    assert 'merged = {"summary": "任务执行完成"' not in orchestrator_source
    assert "def merge_task_results(subtasks: list" in results_source
    assert "get_app_attr(" not in results_source
    assert "call_app_factory(" not in results_source
    assert "from web.app" not in results_source


def test_task_orchestrator_line_budget_does_not_regress():
    assert len(_read(TASK_ORCHESTRATOR).splitlines()) <= TASK_ORCHESTRATOR_LINE_BUDGET


def test_web_service_migration_candidates_cover_current_boundaries():
    source = _read(WEB_SERVICE_MIGRATION_CANDIDATES)

    required_terms = [
        "web/file_task_stream.py",
        "web/services/chat_stream/orchestrator.py",
        "web/services/chat_stream/agent_handler.py",
        "web/services/chat_stream/langgraph_bridge.py",
        "web/services/chat_stream/generate/regular_handler.py",
        "web/services/chat_stream/generate/system_handler.py",
        "web/services/chat_stream/generate/web_search_handler.py",
        "FileTaskRuntime",
        "SmartDispatcher",
        "LangGraphAgent",
        "UnifiedAgent",
        "web.runtime_context",
        "direct `web.app`",
    ]

    for term in required_terms:
        assert term in source


def test_task_orchestrator_filegen_lives_outside_orchestrator_class():
    orchestrator_source = _read(TASK_ORCHESTRATOR)
    filegen_source = _read(TASK_ORCHESTRATOR_FILEGEN)

    assert (
        "from web.task_orchestrator_filegen import execute_file_gen"
        in orchestrator_source
    )
    assert "async def execute_file_gen(" in filegen_source
    assert "from app.core.services.ppt_generation_service import" in filegen_source
    assert "PPTGenerationService," in filegen_source
    assert "parse_ppt_outline_markdown(text_out)" in filegen_source
    assert "choose_ppt_theme(user_input)" in filegen_source
    assert "PPTGenerationService().generate_from_outline(" in filegen_source
    assert "from app.core.services.ppt_generator import" not in filegen_source
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
    assert (
        "from app.core.services.ppt_generation_service import PPTGenerationService"
        in ppt_source
    )
    assert "PPTGenerationService(" in ppt_source
    assert "from app.core.services.ppt_master import" not in ppt_source
    assert "from app.core.services.ppt_generator import" not in ppt_source
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


def test_workflow_api_uses_core_executor_registry():
    workflow_api_source = _read(WORKFLOW_API_BP)
    execution_source = _read(WORKFLOW_EXECUTION)
    registry_source = _read(WORKFLOW_EXECUTOR_REGISTRY)

    assert "from app.core.workflows.execution import" in workflow_api_source
    assert "prepare_workflow_execution(workflow_id)" in workflow_api_source
    assert "iter_workflow_events(execution_plan, params)" in workflow_api_source
    assert (
        "from app.core.workflows.registry import get_workflow_executor"
        not in workflow_api_source
    )
    assert (
        "from app.core.workflows.registry import get_workflow_executor"
        in execution_source
    )
    assert "def prepare_workflow_execution(workflow_id: str)" in execution_source
    assert "def iter_workflow_events(" in execution_source
    assert (
        "from app.core.workflows.cross_format_extractor import CrossFormatExtractor"
        not in workflow_api_source
    )
    assert "WorkflowExecutorSpec(" in registry_source
    assert "def get_workflow_executor(workflow_id: str)" in registry_source


def test_workflow_api_uses_core_metadata_catalog():
    workflow_api_source = _read(WORKFLOW_API_BP)
    catalog_source = _read(WORKFLOW_CATALOG)
    execution_source = _read(WORKFLOW_EXECUTION)

    assert "from app.core.workflows.catalog import" in workflow_api_source
    assert "list_workflow_definitions()" in workflow_api_source
    assert "get_workflow_definition(workflow_id)" not in workflow_api_source
    assert "is_chat_workflow(workflow_id)" not in workflow_api_source
    assert (
        "from app.core.workflows.catalog import get_workflow_definition, is_chat_workflow"
        in execution_source
    )
    assert "get_workflow_definition(normalized_id)" in execution_source
    assert "is_chat_workflow(normalized_id)" in execution_source
    assert "_WORKFLOW_REGISTRY =" not in workflow_api_source
    assert "WORKFLOW_CATALOG: dict" in catalog_source
    assert "def list_workflow_definitions()" in catalog_source
    assert "def get_workflow_definition(workflow_id: str)" in catalog_source
    assert "def is_chat_workflow(workflow_id: str)" in catalog_source


def test_workflow_api_uses_core_file_store_for_upload_download():
    workflow_api_source = _read(WORKFLOW_API_BP)
    file_store_source = _read(WORKFLOW_FILE_STORE)

    assert "from app.core.workflows.file_store import" in workflow_api_source
    assert "save_workflow_uploads(" in workflow_api_source
    assert "validate_workflow_download_path(" in workflow_api_source
    assert "tempfile.gettempdir" not in workflow_api_source
    assert "WORKFLOW_TEMP_PREFIX" in file_store_source
    assert "def save_workflow_uploads(" in file_store_source
    assert "def validate_workflow_download_path(" in file_store_source


def test_workflow_skill_mapping_is_core_owned_and_documented():
    mapping_source = _read(WORKFLOW_SKILL_MAPPING)
    matrix_source = _read(PPT_WORKFLOW_SKILL_MATRIX)

    required_terms = [
        "WorkflowSkillMapping",
        "WORKFLOW_SKILL_MAPPINGS",
        "get_workflow_candidates_for_skill",
        "get_skill_ids_for_workflow",
        "workflow_has_skill_mapping",
        "cross_format_extractor",
        "doc_smart_compare",
        "questionnaire_filler",
        "data_format_cleaner",
        "multi_doc_synthesis",
        "spreadsheet_analyst",
        "excel_data_cleaner",
        "contract_reviewer",
        "legal_doc_review",
    ]
    for term in required_terms:
        assert term in mapping_source
        assert term in matrix_source


def test_ppt_plugin_uses_core_generation_service_facade():
    plugin_source = _read(PPT_PLUGIN)
    service_source = _read(PPT_GENERATION_SERVICE)
    contract_source = _read(PPT_GENERATION_CONTRACT)

    assert "from app.core.services.ppt_generation_service import" in plugin_source
    assert "PPTGenerationService().plan_outline(" in plugin_source
    assert "PPTGenerationService().generate_from_outline(" in plugin_source
    assert "from app.core.services.ppt_master import" not in plugin_source
    assert "from app.core.services.ppt_generator import" not in plugin_source
    assert "from app.core.services.ppt_generation_contract import" in service_source
    # Service facade now imports PPTContentPlanner/PPTGenerator directly (legacy adapter removed)
    assert (
        "from app.core.services.ppt_master import PPTContentPlanner" in service_source
    )
    assert "from app.core.services.ppt_generator import PPTGenerator" in service_source
    assert "_PPTContentPlanner" in service_source
    assert "_PPTGenerator" in service_source
    assert "normalize_generation_result(result, output_path)" in service_source
    assert "def parse_ppt_outline_markdown(" not in service_source
    assert "def choose_ppt_theme(" not in service_source
    assert "def parse_ppt_outline_markdown(" in contract_source
    assert "def choose_ppt_theme(" in contract_source
    assert "def normalize_generation_result(" in contract_source
    assert "from app.core.services.ppt_master import" not in contract_source
    assert "from app.core.services.ppt_generator import" not in contract_source


def test_template_library_ppt_generation_uses_service_facade():
    template_source = _read(TEMPLATE_LIBRARY)

    assert (
        "from app.core.services.ppt_generation_service import PPTGenerationService"
        in template_source
    )
    assert "PPTGenerationService().generate_outline_result(" in template_source
    assert "from app.core.services.ppt_generator import" not in template_source
    assert "PPTGenerator(" not in template_source


def test_ppt_generator_direct_imports_are_limited_to_service_facade():
    allowed = {
        PPT_GENERATION_SERVICE.relative_to(ROOT).as_posix(),
    }
    offenders = []
    for root in [ROOT / "app", ROOT / "web"]:
        for path in root.rglob("*.py"):
            if path == PPT_GENERATOR:
                continue
            source = _read(path)
            if "from app.core.services.ppt_generator import" in source:
                rel_path = path.relative_to(ROOT).as_posix()
                if rel_path not in allowed:
                    offenders.append(rel_path)

    assert offenders == []


def test_legacy_ppt_pipeline_stays_unwired_from_production_paths():
    offenders = []
    for root in [ROOT / "app", ROOT / "web"]:
        for path in root.rglob("*.py"):
            if path == ROOT / "web" / "ppt_pipeline.py":
                continue
            source = _read(path)
            if (
                "app.core.services.ppt_pipeline" in source
                or "from app.core.services.ppt_pipeline import" in source
            ):
                offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_removed_file_hub_open_endpoint_has_no_compatibility_route():
    source = _read(FILE_HUB_ROUTES)

    assert 'file_hub_bp.route("/open"' not in source
    assert "def removed_native_open_file(" not in source
    assert "def retired_open_file(" not in source


def test_retired_api_aliases_stay_removed():
    document_source = _read(ROOT / "web" / "blueprints" / "document.py")
    feedback_source = _read(ROOT / "web" / "document_feedback.py")
    skill_source = _read(ROOT / "app" / "api" / "skill_routes.py")
    agent_source = _read(ROOT / "app" / "api" / "agent_routes.py")

    assert "/api/document/analyze-annotations" not in document_source
    assert "def analyze_annotations_only(" not in feedback_source
    assert '@skill_bp.route("/<skill_id>/enable"' not in skill_source
    assert "def process_compat(" not in agent_source
    assert "def process_stream_compat(" not in agent_source
    assert "def process():" in agent_source
    assert "def process_stream():" in agent_source


def test_chat_and_session_blueprints_use_explicit_chat_runtime_services():
    for path in [CHAT_BP, SESSIONS_BP]:
        source = _read(path)
        assert "from web.chat_runtime_services import" in source
        assert "from web.runtime_context import" not in source
        assert "import web.app" not in source
        assert "from web.app import" not in source

    settings_source = _read(SETTINGS_BP)
    assert "from web.settings_runtime_services import" in settings_source
    assert "from web.runtime_context import" not in settings_source


def test_session_and_settings_runtime_access_uses_named_helpers():
    for path in [SESSIONS_BP, SETTINGS_BP]:
        source = _read(path)
        assert "get_app_attr(" not in source


def test_chat_runtime_services_do_not_reflect_through_web_app():
    source = _read(ROOT / "web" / "chat_runtime_services.py")

    assert "class ChatRuntimeServices" in source
    assert "web.runtime_context" not in source
    assert "web.app" not in source


def test_settings_runtime_services_keep_app_globals_out_of_routes():
    route_source = _read(SETTINGS_BP)
    service_source = _read(ROOT / "web" / "settings_runtime_services.py")
    bootstrap_source = _read(ROOT / "web" / "settings_runtime_bootstrap.py")

    assert "from web.settings_runtime_services import" in route_source
    assert "from web.runtime_context import" not in route_source
    assert "class SettingsRuntimeServices" in service_source
    assert "web.app" not in service_source
    assert "web.app" not in bootstrap_source


def test_service_blueprints_use_named_runtime_services():
    lazy_service_helpers = [
        "get_behavior_monitor",
        "get_suggestion_engine",
        "get_insight_reporter",
        "get_notification_manager",
        "get_proactive_dialogue",
        "get_context_awareness",
        "get_trigger_system",
        "get_auto_execution",
        "get_knowledge_graph",
        "get_file_editor",
        "get_file_indexer",
        "get_concept_extractor",
        "get_file_organizer",
        "get_file_analyzer",
        "get_batch_ops_manager",
        "get_organize_root",
    ]
    for path in [
        ANALYTICS_BP,
        PROACTIVE_BP,
        EXECUTION_BP,
        KNOWLEDGE_BP,
        FILE_EDITOR_BP,
        FILE_ORGANIZE_BP,
    ]:
        source = _read(path)
        assert "from web.runtime_services import" in source
        assert "call_app_factory(" not in source
        assert "get_app_attr(" not in source
        for helper in lazy_service_helpers:
            assert f"from web.runtime_context import {helper}" not in source


def test_runtime_services_keep_lazy_services_out_of_app_bridge():
    source = _read(ROOT / "web" / "runtime_services.py")
    runtime_context = _read(ROOT / "web" / "runtime_context.py")

    assert 'importlib.import_module("web.app")' not in source
    assert "sys.modules" not in source
    assert "from web.lazy_loaders." in source
    for helper in [
        "get_behavior_monitor",
        "get_suggestion_engine",
        "get_insight_reporter",
        "get_notification_manager",
        "get_proactive_dialogue",
        "get_context_awareness",
        "get_trigger_system",
        "get_auto_execution",
        "get_knowledge_graph",
        "get_file_editor",
        "get_file_indexer",
        "get_concept_extractor",
        "get_file_organizer",
        "get_file_analyzer",
        "get_batch_ops_manager",
        "get_organize_root",
    ]:
        assert f"def {helper}(" in source
        assert f"def {helper}(" not in runtime_context


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
