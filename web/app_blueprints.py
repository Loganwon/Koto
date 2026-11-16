from __future__ import annotations

import importlib
import os
import sys
import threading
from dataclasses import dataclass
from logging import Logger
from typing import Any

from flask import Flask

_blueprints_lock = threading.Lock()
_BLUEPRINT_HEALTH_EXTENSION = "koto_blueprint_registration"

_REQUIRED_BLUEPRINTS = frozenset(
    {
        "Auth",
        "Chat",
        "EditorAI",
        "FileHubAPI",
        "HealthAPI",
        "HTTPWiring",
        "Memory",
        "MiscAPI",
        "Pages",
        "PluginProtocol",
        "PPTDownload",
        "ResponseAPI",
        "Sessions",
        "Settings",
        "TaskAPI",
        "Template",
        "VoiceBP",
        "Workspace",
        "WorkspaceAssistant",
    }
)

_NON_SPEC_BLUEPRINTS = frozenset({"Auth", "HealthAPI", "HTTPWiring", "Memory"})


@dataclass(frozen=True)
class BlueprintSpec:
    module: str
    attribute: str
    tag: str
    prefix: str | None = None
    feature: str | None = None
    csrf_blueprint: bool = False
    csrf_endpoints: tuple[str, ...] = ()


_BLUEPRINT_SPECS = (
    BlueprintSpec(
        "app.api.task_routes",
        "task_bp",
        "TaskAPI",
        "/api/tasks",
    ),
    BlueprintSpec(
        "app.api.plugin_protocol_routes",
        "plugin_protocol_bp",
        "PluginProtocol",
    ),
    BlueprintSpec("web.ppt_api_routes", "ppt_api_bp", "PPTDownload"),
    BlueprintSpec("app.api.goal_routes", "goal_bp", "GoalAPI", "/api/goals", "goals"),
    BlueprintSpec(
        "app.api.file_hub_routes",
        "file_hub_bp",
        "FileHubAPI",
        "/api/files",
    ),
    BlueprintSpec("app.api.job_routes", "job_bp", "JobAPI", feature="jobs"),
    BlueprintSpec(
        "app.api.mcp_routes",
        "mcp_bp",
        "MCPAPI",
        csrf_blueprint=True,
    ),
    BlueprintSpec("app.api.ops_routes", "ops_bp", "OpsAPI"),
    BlueprintSpec("app.api.response_routes", "response_bp", "ResponseAPI"),
    BlueprintSpec(
        "app.api.telegram_bot_routes",
        "telegram_bp",
        "TelegramAPI",
        "/api/telegram",
    ),
    BlueprintSpec("web.blueprints.pages", "pages_bp", "Pages"),
    BlueprintSpec("web.blueprints.sessions", "sessions_bp", "Sessions"),
    BlueprintSpec("web.blueprints.settings", "settings_bp", "Settings"),
    BlueprintSpec("web.blueprints.workspace", "workspace_bp", "Workspace"),
    BlueprintSpec("web.blueprints.voice", "voice_bp", "VoiceBP"),
    BlueprintSpec("web.blueprints.misc_api", "misc_api_bp", "MiscAPI"),
    BlueprintSpec(
        "web.blueprints.file_organize",
        "file_organize_bp",
        "FileOrganize",
        feature="legacy-file-api",
    ),
    BlueprintSpec(
        "web.blueprints.chat",
        "chat_bp",
        "Chat",
        csrf_endpoints=("chat.chat", "chat.chat_stream", "chat.mini_chat"),
    ),
    BlueprintSpec(
        "web.blueprints.editor_ai",
        "editor_ai_bp",
        "EditorAI",
        csrf_endpoints=(
            "editor_ai.editor_ai_task_stream",
            "editor_ai.editor_ai_task_stream_cancel",
            "editor_ai.editor_ai_chart",
        ),
    ),
    BlueprintSpec(
        "web.blueprints.workspace_assistant",
        "workspace_assistant_bp",
        "WorkspaceAssistant",
    ),
    BlueprintSpec(
        "web.blueprints.rag_api",
        "rag_bp",
        "RAG",
        feature="knowledge-base",
        csrf_endpoints=(
            "rag.rag_search",
            "rag.rag_reindex",
            "rag.rag_index_file",
            "rag.rag_index_directory",
            "rag.rag_start_watcher",
            "rag.rag_stop_watcher",
            "rag.rag_kb_set_root",
            "rag.rag_model_config_update",
        ),
    ),
    BlueprintSpec(
        "web.blueprints.template_api",
        "template_bp",
        "Template",
        csrf_endpoints=(
            "template.template_generate",
            "template.template_preview",
            "template.template_placeholders",
        ),
    ),
)


class RequiredBlueprintRegistrationError(RuntimeError):
    """Raised when a released build cannot register a required capability."""


def _validate_blueprint_manifest() -> None:
    """Reject an ambiguous or incomplete route manifest during module import."""
    tags = [spec.tag for spec in _BLUEPRINT_SPECS]
    duplicate_tags = sorted({tag for tag in tags if tags.count(tag) > 1})
    registrations = [
        (spec.module, spec.attribute, spec.prefix) for spec in _BLUEPRINT_SPECS
    ]
    duplicate_registrations = sorted(
        {item for item in registrations if registrations.count(item) > 1}
    )
    known_tags = set(tags) | set(_NON_SPEC_BLUEPRINTS)
    missing_required = sorted(_REQUIRED_BLUEPRINTS - known_tags)
    gated_required = sorted(
        spec.tag
        for spec in _BLUEPRINT_SPECS
        if spec.tag in _REQUIRED_BLUEPRINTS and spec.feature is not None
    )
    invalid_features = sorted(
        spec.tag
        for spec in _BLUEPRINT_SPECS
        if spec.feature is not None
        and (not spec.feature.strip() or spec.feature != spec.feature.lower())
    )
    problems = []
    if duplicate_tags:
        problems.append(f"duplicate tags: {duplicate_tags}")
    if duplicate_registrations:
        problems.append(f"duplicate registrations: {duplicate_registrations}")
    if missing_required:
        problems.append(f"required tags without registrars: {missing_required}")
    if gated_required:
        problems.append(f"required tags cannot be optional: {gated_required}")
    if invalid_features:
        problems.append(f"invalid optional feature names: {invalid_features}")
    if problems:
        raise RuntimeError("Invalid blueprint manifest: " + "; ".join(problems))


_validate_blueprint_manifest()


def _is_release_mode(app: Flask) -> bool:
    return not (
        app.debug
        or app.testing
        or app.config.get("KOTO_ALLOW_DEGRADED_BLUEPRINTS", False)
        or os.environ.get("FLASK_ENV", "").lower() == "development"
    )


def _blueprint_registration_state(app: Flask) -> dict[str, Any]:
    return app.extensions.setdefault(
        _BLUEPRINT_HEALTH_EXTENSION,
        {
            "required": sorted(_REQUIRED_BLUEPRINTS),
            "registered": [],
            "disabled_optional": [],
            "missing_required": [],
            "missing_optional": [],
        },
    )


def _record_blueprint_success(app: Flask, name: str) -> None:
    registered = _blueprint_registration_state(app)["registered"]
    if name not in registered:
        registered.append(name)


def _record_blueprint_failure(
    app: Flask, name: str, module: str, exc: Exception
) -> None:
    state = _blueprint_registration_state(app)
    entry = {"name": name, "module": module, "reason": str(exc)}
    bucket = "missing_required" if name in _REQUIRED_BLUEPRINTS else "missing_optional"
    if entry not in state[bucket]:
        state[bucket].append(entry)
    if name in _REQUIRED_BLUEPRINTS and _is_release_mode(app):
        raise RequiredBlueprintRegistrationError(
            f"Required blueprint '{name}' ({module}) could not be registered: {exc}"
        ) from exc


def _enabled_optional_features(app: Flask) -> set[str]:
    raw = str(
        app.config.get("KOTO_OPTIONAL_FEATURES")
        or os.environ.get("KOTO_OPTIONAL_FEATURES", "")
    ).strip()
    if raw:
        return {item.strip().lower() for item in raw.split(",") if item.strip()}
    # Source runs are development-complete. Frozen release builds start only
    # product-owned routes unless the user or deployment enables an add-on.
    return set() if getattr(sys, "frozen", False) else {"*"}


def _spec_enabled(spec: BlueprintSpec, enabled: set[str]) -> bool:
    return spec.feature is None or "*" in enabled or spec.feature in enabled


def _exempt_csrf_endpoint(app: Flask, endpoint: str) -> None:
    csrf = getattr(app, "extensions", {}).get("csrf")
    exempt = getattr(csrf, "exempt", None)
    view_func = app.view_functions.get(endpoint)
    if callable(exempt) and view_func is not None:
        exempt(view_func)


def _exempt_csrf_blueprint(app: Flask, blueprint: Any) -> None:
    csrf = getattr(app, "extensions", {}).get("csrf")
    exempt = getattr(csrf, "exempt", None)
    if callable(exempt):
        exempt(blueprint)


def _register_spec(app: Flask, logger: Logger, spec: BlueprintSpec) -> Any | None:
    try:
        module = importlib.import_module(spec.module)
        blueprint = getattr(module, spec.attribute)
        if spec.prefix:
            app.register_blueprint(blueprint, url_prefix=spec.prefix)
        else:
            app.register_blueprint(blueprint)
        if spec.csrf_blueprint:
            _exempt_csrf_blueprint(app, blueprint)
        for endpoint in spec.csrf_endpoints:
            _exempt_csrf_endpoint(app, endpoint)
        _record_blueprint_success(app, spec.tag)
        logger.info("[%s] blueprint registered", spec.tag)
        return None
    except Exception as exc:
        _record_blueprint_failure(app, spec.tag, spec.module, exc)
        logger.warning("[%s] blueprint unavailable: %s", spec.tag, exc)
        return None


def _register_health_and_http(app: Flask, logger: Logger) -> None:
    try:
        module = importlib.import_module("web.routes.health")
        app.register_blueprint(module.health_bp)
        _record_blueprint_success(app, "HealthAPI")
    except Exception as exc:
        _record_blueprint_failure(app, "HealthAPI", "web.routes.health", exc)

    try:
        from web.app_http import configure_http_wiring

        configure_http_wiring(app, logger)
        _record_blueprint_success(app, "HTTPWiring")
    except Exception as exc:
        _record_blueprint_failure(app, "HTTPWiring", "web.app_http", exc)
        logger.error("[HTTP] wiring failed: %s", exc)


def _register_auth(app: Flask, logger: Logger) -> None:
    try:
        module = importlib.import_module("web.blueprints.auth")
        module.register_auth_routes(app)
        _record_blueprint_success(app, "Auth")
    except Exception as exc:
        _record_blueprint_failure(app, "Auth", "web.blueprints.auth", exc)
        logger.warning("[Auth] routes unavailable: %s", exc)


def _register_function_routes(app: Flask, logger: Logger) -> None:
    function_routes = (
        (
            "Memory",
            "web.blueprints.memory_api",
            "register_memory_routes",
            lambda: importlib.import_module("web.memory_runtime").get_memory_manager,
        ),
    )
    for tag, module_name, function_name, dependency_factory in function_routes:
        try:
            function = getattr(importlib.import_module(module_name), function_name)
            if dependency_factory is None:
                function(app)
            else:
                function(app, dependency_factory())
            _record_blueprint_success(app, tag)
        except Exception as exc:
            _record_blueprint_failure(app, tag, module_name, exc)
            logger.warning("[%s] routes unavailable: %s", tag, exc)


def register_blueprints_deferred(app: Flask, logger: Logger):
    """Register one manifest-controlled HTTP surface for this Flask app."""
    with _blueprints_lock:
        state = _blueprint_registration_state(app)
        if state.get("registration_started"):
            return None
        state["registration_started"] = True

    enabled = _enabled_optional_features(app)
    active_specs = [spec for spec in _BLUEPRINT_SPECS if _spec_enabled(spec, enabled)]
    disabled_specs = [spec for spec in _BLUEPRINT_SPECS if spec not in active_specs]
    state["disabled_optional"] = [
        {"name": spec.tag, "feature": spec.feature} for spec in disabled_specs
    ]

    _register_health_and_http(app, logger)
    _register_auth(app, logger)

    for spec in active_specs:
        _register_spec(app, logger, spec)

    _register_function_routes(app, logger)
    logger.info(
        "[INIT] blueprint surface ready: registered=%d disabled_optional=%d",
        len(state["registered"]),
        len(state["disabled_optional"]),
    )
    return None
