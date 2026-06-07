from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB_APP = ROOT / "web" / "app.py"
APP_BLUEPRINTS = ROOT / "web" / "app_blueprints.py"
KOTO_SPEC = ROOT / "koto.spec"
EDITOR_AI_BP = ROOT / "web" / "blueprints" / "editor_ai.py"
FILE_TASK_STREAM = ROOT / "web" / "file_task_stream.py"
CHAT_BP = ROOT / "web" / "blueprints" / "chat.py"
SESSIONS_BP = ROOT / "web" / "blueprints" / "sessions.py"
PPT_LEGACY_BP = ROOT / "web" / "blueprints" / "ppt_legacy.py"
PPT_API_ROUTES = ROOT / "web" / "ppt_api_routes.py"
SETTINGS_BP = ROOT / "web" / "blueprints" / "settings.py"
PAGES_BP = ROOT / "web" / "blueprints" / "pages.py"

EXPECTED_WEB_APP_ROUTES: set[str] = set()


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


def test_web_app_line_budget_does_not_regress():
    """The app module is still large; keep new work out while migration continues."""
    assert len(_read(WEB_APP).splitlines()) <= 14700


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
    assert "web.blueprints.ppt_legacy" in source
    assert "web.blueprints.voice" in source


def test_editor_ai_blueprint_uses_runtime_context_not_web_app_imports():
    source = _read(EDITOR_AI_BP)

    assert "from web.runtime_context import" in source
    assert "import web.app" not in source
    assert "from web.app import" not in source
    assert "_stream_file_task_request" not in source


def test_file_task_stream_lives_outside_web_app():
    """File task SSE orchestration belongs in web.file_task_stream, not web/app.py."""
    app_source = _read(WEB_APP)
    stream_source = _read(FILE_TASK_STREAM)

    assert "def stream_file_task_request(" in stream_source
    assert "def _stream_file_task_request(" not in app_source
    assert "def _safe_file_task_event_dict(" not in app_source
    assert "def _file_task_event_to_safe_sse(" not in app_source
    assert "_FILE_TASK_CONTRACT" not in app_source


def test_ppt_api_handlers_stay_outside_web_app():
    """PPT session/download handlers belong to PPT blueprints and route modules."""
    app_source = _read(WEB_APP)
    ppt_source = _read(PPT_API_ROUTES)
    legacy_source = _read(PPT_LEGACY_BP)

    assert "def download_ppt():" not in app_source
    assert "def get_ppt_session(" not in app_source
    assert '@ppt_api_bp.route("/session/<session_id>", methods=["GET"])' in ppt_source
    assert '@ppt_api_bp.route("/download/<session_id>", methods=["GET"])' in ppt_source
    assert '@ppt_legacy_bp.route("/api/ppt/download", methods=["POST"])' in legacy_source


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


def test_chat_session_and_ppt_blueprints_use_runtime_context():
    for path in [CHAT_BP, SESSIONS_BP, PPT_LEGACY_BP, SETTINGS_BP]:
        source = _read(path)
        assert "from web.runtime_context import" in source
        assert "import web.app" not in source
        assert "from web.app import" not in source


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
