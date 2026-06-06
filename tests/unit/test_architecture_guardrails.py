from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB_APP = ROOT / "web" / "app.py"
APP_BLUEPRINTS = ROOT / "web" / "app_blueprints.py"
KOTO_SPEC = ROOT / "koto.spec"
EDITOR_AI_BP = ROOT / "web" / "blueprints" / "editor_ai.py"
CHAT_BP = ROOT / "web" / "blueprints" / "chat.py"
SESSIONS_BP = ROOT / "web" / "blueprints" / "sessions.py"
PPT_LEGACY_BP = ROOT / "web" / "blueprints" / "ppt_legacy.py"
SETTINGS_BP = ROOT / "web" / "blueprints" / "settings.py"

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
    assert len(_read(WEB_APP).splitlines()) <= 16350


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


def test_chat_session_and_ppt_blueprints_use_runtime_context():
    for path in [CHAT_BP, SESSIONS_BP, PPT_LEGACY_BP, SETTINGS_BP]:
        source = _read(path)
        assert "from web.runtime_context import" in source
        assert "import web.app" not in source
        assert "from web.app import" not in source


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
    ]
    for term in retired_terms:
        assert term not in spec
