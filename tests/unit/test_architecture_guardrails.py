from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_APP = ROOT / "web" / "app.py"
APP_BLUEPRINTS = ROOT / "web" / "app_blueprints.py"
KOTO_SPEC = ROOT / "koto.spec"
EDITOR_AI_BP = ROOT / "web" / "blueprints" / "editor_ai.py"
FILE_TASK_STREAM = ROOT / "app" / "core" / "services" / "file_task_stream.py"
MEMORY_RUNTIME = ROOT / "web" / "memory_runtime.py"
WEB_SERVICE_MIGRATION_CANDIDATES = ROOT / "docs" / "WEB_SERVICE_MIGRATION_CANDIDATES.md"
WORKFLOW_API_BP = ROOT / "web" / "blueprints" / "workflow_api.py"
WORKFLOW_CATALOG = ROOT / "app" / "core" / "workflows" / "catalog.py"
WORKFLOW_EXECUTION = ROOT / "app" / "core" / "workflows" / "execution.py"
WORKFLOW_EXECUTOR_REGISTRY = ROOT / "app" / "core" / "workflows" / "registry.py"
WORKFLOW_FILE_STORE = ROOT / "app" / "core" / "workflows" / "file_store.py"
RETIRED_WORKFLOW_MAPPING = ROOT / "app" / "core" / "workflows" / "skill_mapping.py"
PPT_WORKFLOW_ROUTE_MATRIX = ROOT / "docs" / "PPT_WORKFLOW_ROUTE_MATRIX.md"
PPT_PLUGIN = ROOT / "app" / "core" / "agent" / "toolkits" / "builtin" / "ppt_plugin.py"
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
TEST_WEB_APP_COVERAGE = ROOT / "tests" / "unit" / "test_web_app_coverage.py"
TEST_WEB_APP_UTILS = ROOT / "tests" / "unit" / "test_web_app.py"

EXPECTED_WEB_APP_ROUTES: set[str] = set()
WEB_APP_LINE_BUDGET = 1120
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


def test_retired_task_router_training_surface_stays_deleted():
    app_blueprints = _read(APP_BLUEPRINTS)
    retired = (
        "app/api/training_routes.py",
        "app/core/learning/training_data_builder.py",
        "app/core/learning/training_db.py",
        "app/core/learning/synthetic_data_generator.py",
        "app/core/learning/memory_to_training.py",
        "app/core/agent/file_task_classification/__init__.py",
        "app/core/routing/ai_router.py",
    )

    assert all(not (ROOT / path).exists() for path in retired)
    assert "training_routes" not in app_blueprints
    assert "KOTO_DEV_TRAINING" not in app_blueprints


def test_web_app_line_budget_does_not_regress():
    """The app module is still large; keep new work out while migration continues."""
    assert len(_read(WEB_APP).splitlines()) <= WEB_APP_LINE_BUDGET


def test_web_app_does_not_restore_dead_prompt_and_shortcut_tables():
    source = _read(WEB_APP)

    assert "def _get_system_instruction(" not in source
    assert "def _get_filegen_brief_instruction(" not in source
    assert "TASK_PROMPTS =" not in source
    assert "WINDOWS_SHORTCUTS =" not in source


def test_web_app_notification_socket_uses_the_core_service_owner():
    source = _read(WEB_APP)

    assert (
        "from app.core.services.notification_manager import get_notification_manager"
        in source
    )


def test_web_app_model_threads_use_the_managed_runtime_lifecycle():
    app_source = _read(WEB_APP)
    runtime_source = _read(ROOT / "web" / "app_runtime.py")

    assert "start_model_runtime(" in app_source
    assert 'name="ModelManagerInit"' not in app_source
    assert 'name="ModelManagerRefresh"' not in app_source
    assert "def start_model_runtime(" in runtime_source
    assert "_background_runtime_disabled()" in runtime_source
    assert "start_proxy_warmup(" in app_source
    assert "threading.Thread(" not in app_source


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
    brain_source = _read(ROOT / "app" / "core" / "brain_pkg" / "__init__.py")
    app_source = _read(WEB_APP)

    assert "class BrainRuntimeServices" in brain_source
    assert "web.runtime_context" not in brain_source
    assert "configure_default_brain_runtime(" in app_source
    assert "BrainRuntimeServices(" in app_source


def test_task_api_does_not_restore_the_parallel_background_file_queue():
    source = _read(TASK_ROUTES)

    assert '@task_bp.post("/submit")' not in source
    assert "app.core.services.task_queue" not in source
    assert "from web.runtime_context import stream_file_task_request" not in source


def test_core_llm_provider_helpers_do_not_reflect_through_web_runtime_context():
    source = _read(ROOT / "app" / "core" / "agent" / "llm_provider_helpers.py")

    assert (
        "from app.core.llm.model_selection import get_configured_cloud_model" in source
    )
    assert "web.runtime_context" not in source


def test_memory_tools_plugin_uses_the_core_service_owner_directly():
    source = _read(
        ROOT
        / "app"
        / "core"
        / "agent"
        / "toolkits"
        / "builtin"
        / "memory_tools_plugin.py"
    )

    assert "from app.core.services.memory_manager import get_memory_manager" in source
    assert "web.memory_runtime" not in source
    assert "EnhancedMemoryManager()" not in source


def test_retired_app_context_stays_deleted():
    assert not (ROOT / "app" / "core" / "app_context.py").exists()

    for source_root in (ROOT / "app", ROOT / "web", ROOT / "launcher"):
        for path in source_root.rglob("*.py"):
            assert "app.core.app_context" not in _read(path), path


def test_production_agent_construction_has_one_owner():
    owner = ROOT / "app" / "core" / "agent" / "kernel_agent_service.py"
    assert "create_agent" in _read(owner)
    assert "create_local_agent" in _read(owner)

    consumers = (
        ROOT / "web" / "services" / "chat_stream" / "agent_handler.py",
        ROOT / "app" / "core" / "goal" / "goal_job_handler.py",
        ROOT / "app" / "core" / "services" / "morning_brief.py",
        ROOT / "app" / "core" / "jobs" / "job_runner.py",
    )
    for path in consumers:
        source = _read(path)
        assert "get_kernel_agent" in source, path
        assert "app.core.agent.factory" not in source, path
        assert "KernelAgent(" not in source, path

    goal_manager_source = _read(ROOT / "app" / "core" / "goal" / "goal_manager.py")
    assert "_execute_goal_direct" not in goal_manager_source
    assert "GoalExec-" not in goal_manager_source
    assert "get_kernel_agent" not in goal_manager_source

    supervision = _read(ROOT / "app" / "core" / "agent" / "koto_supervision.py")
    assert "app.core.agent.factory" not in supervision
    assert "build_tool_registry" in supervision


def test_rag_lifecycles_are_owned_by_core_service_factories():
    rag_source = _read(ROOT / "app" / "core" / "services" / "rag_service.py")
    indexer_source = _read(ROOT / "app" / "core" / "services" / "file_rag_indexer.py")

    assert "_rag_instances" in rag_source
    assert "def get_rag_service(" in rag_source
    assert "def get_file_rag_indexer(" in indexer_source
    assert "get_rag_service(index_dir=self._index_dir)" in indexer_source

    consumers = (
        ROOT / "web" / "blueprints" / "rag_api.py",
        ROOT / "app" / "core" / "services" / "kb_config.py",
        ROOT / "app" / "core" / "services" / "memory_manager.py",
        ROOT / "app" / "core" / "file" / "file_registry.py",
    )
    for path in consumers:
        source = _read(path)
        assert "RAGService(" not in source, path
        assert "FileRAGIndexer(" not in source, path


def test_system_info_service_is_core_owned_and_prompt_uses_tools_on_demand():
    performance_plugin = _read(
        ROOT
        / "app"
        / "core"
        / "agent"
        / "toolkits"
        / "builtin"
        / "performance_analysis_plugin.py"
    )
    system_info_plugin = _read(
        ROOT
        / "app"
        / "core"
        / "agent"
        / "toolkits"
        / "builtin"
        / "system_info_plugin.py"
    )
    core_service = _read(ROOT / "app" / "core" / "services" / "system_info.py")
    system_instruction = _read(
        ROOT / "app" / "core" / "services" / "chat_system_instruction.py"
    )

    expected_import = (
        "from app.core.services.system_info import get_system_info_collector"
    )
    assert expected_import in performance_plugin
    assert expected_import in system_info_plugin
    assert "from web.system_info import" not in performance_plugin
    assert "from web.system_info import" not in system_info_plugin
    assert "class SystemInfoCollector:" in core_service
    assert "get_formatted_system_info" not in system_instruction
    assert "只有任务需要时才调用工具" in system_instruction
    assert not (ROOT / "app/core/services/context_injector.py").exists()
    assert not (ROOT / "web" / "system_info.py").exists()


def test_core_to_web_import_debt_does_not_expand():
    """Forbid transport-layer imports from Core production modules."""
    allowed = set()
    offenders = set()

    for path in (ROOT / "app" / "core").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        imports_web = any(
            (
                isinstance(node, ast.Import)
                and any(
                    alias.name == "web" or alias.name.startswith("web.")
                    for alias in node.names
                )
            )
            or (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and (node.module == "web" or node.module.startswith("web."))
            )
            for node in ast.walk(tree)
        )
        if imports_web:
            offenders.add(path.relative_to(ROOT).as_posix())

    assert offenders == allowed


def test_graph_rag_receives_knowledge_graph_at_the_composition_boundary():
    graph_rag_source = _read(
        ROOT / "app" / "core" / "services" / "graph_rag_service.py"
    )
    app_source = _read(WEB_APP)

    assert "def configure_knowledge_graph_factory(" in graph_rag_source
    assert "from web." not in graph_rag_source
    assert "configure_knowledge_graph_factory(KnowledgeGraph)" in app_source


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

    assert "from web.shared import (" in app_source
    assert "from web.shared import invalidate_settings_cache" in settings_route
    assert not (ROOT / "web" / "runtime_services.py").exists()
    assert not list((ROOT / "web" / "lazy_loaders").glob("*.py"))
    assert not (ROOT / "web" / "config" / "__init__.py").exists()


def test_duplicate_startup_module_stays_deleted():
    assert not (ROOT / "web" / "app_startup.py").exists()


def test_retired_skill_recorder_stays_removed():
    assert not (ROOT / "app" / "core" / "skills" / "skill_recorder.py").exists()


def test_job_runner_proactive_llm_uses_core_provider_boundary():
    source = _read(ROOT / "app" / "core" / "jobs" / "job_runner.py")

    assert "from app.core.llm.provider_factory import get_llm_provider" in source
    assert (
        "from app.core.llm.model_selection import get_configured_cloud_model" in source
    )
    assert "web.runtime_context" not in source
    assert "get_client_proxy" not in source
    assert ".models.generate_content(" not in source


def test_core_does_not_import_web_runtime_context():
    offenders = set()
    for path in (ROOT / "app" / "core").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        imports_runtime_context = any(
            (
                isinstance(node, ast.Import)
                and any(alias.name == "web.runtime_context" for alias in node.names)
            )
            or (
                isinstance(node, ast.ImportFrom)
                and (
                    node.module == "web.runtime_context"
                    or (
                        node.module == "web"
                        and any(alias.name == "runtime_context" for alias in node.names)
                    )
                )
            )
            for node in ast.walk(tree)
        )
        if imports_runtime_context:
            offenders.add(path.relative_to(ROOT).as_posix())

    assert offenders == set()


def test_retired_ppt_orchestration_modules_stay_deleted():
    retired = (
        "ppt_pipeline.py",
        "ppt_synthesizer.py",
        "ppt_quality.py",
        "ppt_generator_enhanced.py",
    )

    for filename in retired:
        assert not (ROOT / "app" / "core" / "services" / filename).exists()


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
    assert "is_simple_query(" not in handler_source
    assert "first_token_timeout_seconds(task_type)" in handler_source
    assert "def select_regular_model(" in policy_source
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

    assert "_BLUEPRINT_SPECS" in source
    assert "class BlueprintSpec" in source
    assert "web.blueprints.workspace_assistant" in source
    assert "app.api.mcp_routes" in source
    assert "web.blueprints.editor_ai" in source
    assert "web.blueprints.voice" in source
    assert '"register_memory_routes"' in source


def test_compat_route_registrars_use_blueprints_internally():
    """Compatibility registrars may remain, but business routes should be blueprint-owned."""
    auth_source = _read(AUTH_ROUTES)
    memory_source = _read(MEMORY_API_ROUTES)

    for source in [auth_source, memory_source]:
        assert "@app.route" not in source
        assert ".register_blueprint(" in source
        assert "Blueprint(" in source


def test_editor_ai_blueprint_uses_stream_boundary_not_runtime_service_locator():
    source = _read(EDITOR_AI_BP)

    assert "from web.runtime_context import" not in source
    assert "import web.app" not in source
    assert "from web.app import" not in source
    assert "get_app_attr(" not in source
    assert "_stream_file_task_request" not in source
    assert (
        "from app.core.services.file_task_stream import stream_file_task_request"
        in source
    )
    assert "from app.core.services.editor_ai_text import clean_selection_text" in source
    runtime_source = _read(ROOT / "web" / "runtime_context.py")
    assert "def stream_file_task_request(" not in runtime_source
    assert "def safe_editor_sse(" not in runtime_source
    stream_source = _read(FILE_TASK_STREAM)
    assert (
        "from web.blueprints.editor_ai import _clean_selection_text"
        not in stream_source
    )


def test_file_task_stream_lives_outside_web_app():
    """File task SSE orchestration belongs in the Core service, not web/app.py."""
    app_source = _read(WEB_APP)
    stream_source = _read(ROOT / "app" / "core" / "services" / "file_task_stream.py")

    assert "def stream_file_task_request(" in stream_source
    assert not (ROOT / "web/file_task_stream.py").exists()
    assert (
        "from app.core.config.workspace_runtime import get_workspace_root"
        in stream_source
    )
    assert "service_registry" not in stream_source
    assert "gemini_client" not in stream_source
    assert "from web." not in stream_source
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
    assert '@ppt_api_bp.route("/download/<session_id>", methods=["GET"])' in ppt_source
    assert '@ppt_api_bp.route("/session/<session_id>"' not in ppt_source
    assert "PPTGenerationService" not in ppt_source
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
    web_searcher_source = _read(ROOT / "web" / "knowledge" / "web_searcher.py")

    assert "class WebSearcher" not in app_source
    assert "from web.knowledge.web_searcher import WebSearcher" in app_source
    assert "class WebSearcher" in web_searcher_source


def test_programmatic_free_text_routing_family_stays_deleted():
    app_source = _read(WEB_APP)
    retired = (
        "app/core/services/context_analyzer.py",
        "app/core/routing/smart_dispatcher.py",
        "app/core/routing/routing_rule_chain.py",
        "app/core/routing/rule_router.py",
        "app/core/routing/routing_config.py",
        "app/core/routing/task_classifier.py",
        "app/core/routing/intent_analyzer.py",
        "app/core/routing/local_model_router.py",
        "app/core/routing/ai_router.py",
        "app/api/training_routes.py",
        "app/core/learning/training_data_builder.py",
        "app/core/learning/training_db.py",
        "app/core/learning/synthetic_data_generator.py",
        "app/core/learning/memory_to_training.py",
        "scripts/extract_classifier_data.py",
        "scripts/train_task_classifier.py",
        "models/task_classifier/clf.pkl",
        "models/task_classifier/label_encoder.pkl",
    )

    assert all(not (ROOT / path).exists() for path in retired)
    assert "SmartDispatcher" not in app_source
    assert "ContextAnalyzer" not in app_source


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
    assert "from web.session_manager import SessionManager" not in app_source
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
    assert '"register_memory_routes"' in registry_source
    assert '"register_parallel_api"' not in registry_source
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


def test_retired_task_orchestrator_family_stays_deleted():
    retired_paths = (
        "web/task_orchestrator.py",
        "web/task_orchestrator_filegen.py",
        "web/task_orchestrator_ppt.py",
        "web/task_orchestrator_quality.py",
        "web/task_orchestrator_results.py",
        "web/task_orchestrator_runtime.py",
        "web/task_orchestrator_search.py",
        "web/task_orchestrator_steps.py",
        "web/tasks/task_orchestrator.py",
        "web/tasks/task_orchestrator_filegen.py",
        "web/tasks/task_orchestrator_ppt.py",
        "web/tasks/task_orchestrator_quality.py",
        "web/tasks/task_orchestrator_results.py",
        "web/tasks/task_orchestrator_runtime.py",
        "web/tasks/task_orchestrator_search.py",
        "web/tasks/task_orchestrator_steps.py",
    )

    assert all(not (ROOT / path).exists() for path in retired_paths)


def test_retired_background_agent_chain_stays_deleted():
    assert not (ROOT / "app/api/bg_agent_routes.py").exists()
    assert not (ROOT / "app/core/agent/background_agent.py").exists()


def test_retired_file_task_model_tool_routes_stay_deleted():
    agent_root = ROOT / "app" / "core" / "agent"
    retired = (
        "file_task_execution_loop.py",
        "file_task_doc_annotate_runner.py",
        "file_task_docx_stepwise_runner.py",
        "file_task_doc_annotate_fallback.py",
        "file_task_readonly_loop_guard.py",
        "file_task_guard_emission.py",
        "file_task_evidence_runtime.py",
        "file_task_intent_adjudicator.py",
    )

    assert all(not (agent_root / name).exists() for name in retired)


def test_web_service_migration_candidates_cover_current_boundaries():
    assert not WEB_SERVICE_MIGRATION_CANDIDATES.exists()


def test_workflow_api_uses_core_executor_registry():
    assert not WORKFLOW_API_BP.exists()


def test_retired_parallel_workflow_surface_stays_deleted():
    retired_paths = (
        "app/core/workflow/__init__.py",
        "app/core/workflow/workflow_state.py",
        "app/core/services/task_queue.py",
        "web/blueprints/parallel_api.py",
        "web/parallel_executor.py",
        "web/static/workflow_dag.html",
    )
    blueprint_source = _read(APP_BLUEPRINTS)

    assert all(not (ROOT / path).exists() for path in retired_paths)
    assert "concurrent.futures" not in blueprint_source
    assert "ThreadPoolExecutor" not in blueprint_source
    assert "preload" not in blueprint_source

    task_routes = _read(ROOT / "app" / "api" / "task_routes.py")
    runtime_source = _read(ROOT / "web" / "app_runtime.py")
    assert '@task_bp.post("/submit")' not in task_routes
    assert "task_queue" not in runtime_source


def test_unreferenced_legacy_vendor_bundles_stay_deleted():
    retired_assets = (
        "web/static/vendor/d3/d3.v7.min.js",
        "web/static/vendor/font-awesome/6.0.0/css/all.min.css",
        "web/static/vendor/font-awesome/6.0.0/webfonts/fa-brands-400.woff2",
        "web/static/vendor/font-awesome/6.0.0/webfonts/fa-regular-400.woff2",
        "web/static/vendor/font-awesome/6.0.0/webfonts/fa-solid-900.woff2",
        "web/static/vendor/font-awesome/6.0.0/webfonts/fa-v4compatibility.woff2",
        "web/static/vendor/tailwindcss/tailwind-play-cdn.js",
    )

    assert all(not (ROOT / path).exists() for path in retired_assets)


def test_workflow_api_uses_core_metadata_catalog():
    assert not WORKFLOW_API_BP.exists()


def test_workflow_api_uses_core_file_store_for_upload_download():
    assert not WORKFLOW_API_BP.exists()


def test_retired_workflow_skill_mapping_stays_out_of_runtime():
    assert not RETIRED_WORKFLOW_MAPPING.exists()
    assert PPT_WORKFLOW_ROUTE_MATRIX.exists()


def test_ppt_plugin_uses_core_generation_service_facade():
    assert not PPT_PLUGIN.exists()


def test_template_library_ppt_generation_uses_service_facade():
    template_source = _read(ROOT / "web" / "tasks" / "template_library.py")

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
    assert not (ROOT / "app" / "core" / "services" / "ppt_pipeline.py").exists()
    assert not (ROOT / "web" / "ppt_pipeline.py").exists()


def test_removed_file_hub_open_endpoint_has_no_compatibility_route():
    source = _read(FILE_HUB_ROUTES)

    assert 'file_hub_bp.route("/open"' not in source
    assert "def removed_native_open_file(" not in source
    assert "def retired_open_file(" not in source


def test_retired_api_aliases_stay_removed():
    assert not (ROOT / "web" / "blueprints" / "document.py").exists()
    assert not (ROOT / "web" / "document_feedback.py").exists()
    assert not (ROOT / "app" / "api" / "skill_routes.py").exists()
    assert not (ROOT / "app" / "api" / "agent_routes.py").exists()


def test_chat_and_session_blueprints_use_the_service_registry():
    for path in [CHAT_BP, SESSIONS_BP]:
        source = _read(path)
        assert "from web.runtime_context import service_registry" in source
        assert "chat_runtime_services" not in source
        assert "import web.app" not in source
        assert "from web.app import" not in source

    settings_source = _read(SETTINGS_BP)
    assert "from web.runtime_context import service_registry" in settings_source
    assert "settings_runtime_services" not in settings_source


def test_session_and_settings_runtime_access_uses_named_helpers():
    for path in [SESSIONS_BP, SETTINGS_BP]:
        source = _read(path)
        assert "get_app_attr(" not in source


def test_retired_chat_runtime_services_stays_deleted():
    assert not (ROOT / "web" / "chat_runtime_services.py").exists()


def test_session_storage_owns_an_explicit_directory_not_an_app_callback():
    source = _read(ROOT / "web" / "session_manager.py")

    assert "def set_chat_dir(" in source
    assert "def get_chat_dir(" in source
    assert "_chat_dir_provider" not in source
    assert "from web.app" not in source


def test_workspace_runtime_has_no_mutable_web_path_mirror():
    shared_source = _read(ROOT / "web" / "shared.py")
    workspace_source = _read(ROOT / "web" / "blueprints" / "workspace.py")
    assistant_source = _read(ROOT / "web" / "blueprints" / "workspace_assistant.py")

    assert "WORKSPACE_DIR =" not in shared_source
    assert "global WORKSPACE_DIR" not in shared_source
    assert "get_workspace_root" in workspace_source
    assert "get_workspace_root" in assistant_source
    assert "from web.shared import WORKSPACE_DIR" not in workspace_source
    assert "from web.shared import WORKSPACE_DIR" not in assistant_source


def test_settings_routes_use_the_single_service_registry():
    route_source = _read(SETTINGS_BP)

    assert "from web.runtime_context import service_registry" in route_source
    assert "settings_runtime_services" not in route_source
    assert not (ROOT / "web" / "settings_runtime_services.py").exists()
    assert not (ROOT / "web" / "settings_runtime_bootstrap.py").exists()


def test_service_blueprints_use_named_runtime_services():
    for path in [FILE_ORGANIZE_BP]:
        source = _read(path)
        assert "from web.runtime_context import service_registry" in source
        assert "service_registry.batch_ops_manager" in source
        assert "from web.runtime_services import" not in source
        assert "call_app_factory(" not in source
        assert "get_app_attr(" not in source

    assert not ANALYTICS_BP.exists()
    assert not PROACTIVE_BP.exists()
    assert not EXECUTION_BP.exists()
    assert not FILE_EDITOR_BP.exists()
    assert not KNOWLEDGE_BP.exists()


def test_service_registry_is_the_only_web_service_cache():
    runtime_context = _read(ROOT / "web" / "runtime_context.py")

    assert "def register_factory(" in runtime_context
    assert "def resolve(" in runtime_context
    assert 'service_registry.register_factory("batch_ops_manager"' in runtime_context
    assert not (ROOT / "web" / "runtime_services.py").exists()
    assert not list((ROOT / "web" / "lazy_loaders").glob("*.py"))


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
    assert not (ROOT / "src" / "rth_voice_fallback.py").exists()
    assert "rth_voice_fallback.py" not in spec
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
    assert not (ROOT / "config" / "file_task_followups.json").exists()


def test_migrated_file_owners_do_not_return_as_web_compatibility_modules():
    retired_web_owners = [
        ROOT / "web" / "file_parser.py",
        ROOT / "web" / "file_watcher.py",
        ROOT / "web" / "blueprints" / "pptx_editor.py",
    ]
    canonical_owners = [
        ROOT / "app" / "core" / "file" / "file_parser.py",
        ROOT / "app" / "core" / "file" / "file_watcher.py",
        ROOT / "app" / "core" / "file" / "pptx_editor.py",
    ]

    assert all(not path.exists() for path in retired_web_owners)
    assert all(path.is_file() for path in canonical_owners)


def test_tests_and_current_docs_do_not_import_retired_file_entrypoints():
    forbidden = (
        "from web." + "file_parser import",
        "from web." + "file_watcher import",
        "from web.blueprints." + "pptx_editor import",
    )
    offenders = []
    for root in (ROOT / "tests", ROOT / "docs"):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".md"}:
                continue
            if "archive" in path.parts:
                continue
            source = _read(path)
            if any(term in source for term in forbidden):
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
