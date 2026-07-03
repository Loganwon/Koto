# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import re
from pathlib import Path

import pytest
from flask import Flask
from werkzeug.routing import RequestRedirect
from werkzeug.routing import MapAdapter


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def _app_from_deferred_loader() -> Flask:
    import web.app_blueprints as app_blueprints

    previous = app_blueprints._blueprints_registered
    try:
        app_blueprints._blueprints_registered = False
        app = Flask(__name__)
        app_blueprints.register_blueprints_deferred(app, _NullLogger())
        return app
    finally:
        app_blueprints._blueprints_registered = previous


def _app_from_service_loader() -> Flask:
    import web.services.blueprint_loader as blueprint_loader

    had_previous = hasattr(blueprint_loader, "_blueprints_registered")
    previous = getattr(blueprint_loader, "_blueprints_registered", False)
    try:
        blueprint_loader._blueprints_registered = False
        app = Flask(__name__)
        blueprint_loader.register_all_blueprints(app, _NullLogger())
        return app
    finally:
        if had_previous:
            blueprint_loader._blueprints_registered = previous
        elif hasattr(blueprint_loader, "_blueprints_registered"):
            delattr(blueprint_loader, "_blueprints_registered")


def _adapter(app: Flask) -> MapAdapter:
    return app.url_map.bind("localhost")


def _assert_route(adapter: MapAdapter, method: str, path: str) -> None:
    adapter.match(path, method=method)


def _frontend_api_refs() -> set[tuple[str, str]]:
    pattern = re.compile(r"['\"](/api/[A-Za-z0-9_./{}?=&:%+-]+)['\"]")
    paths = [
        *Path("web").rglob("*.js"),
        *Path("web").rglob("*.ts"),
        *Path("web").rglob("*.html"),
    ]
    refs: set[tuple[str, str]] = set()
    for path in paths:
        if "node_modules" in path.parts:
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in pattern.finditer(text):
            api_path = match.group(1).split("?", 1)[0]
            if api_path == "/api/":
                continue
            if api_path.endswith("/") and "${" not in api_path and "{" not in api_path:
                continue
            api_path = re.sub(r"\$\{[^}]+\}", "x", api_path)
            api_path = re.sub(r"\{[^}]+\}", "x", api_path)
            refs.add((str(path), api_path))
    return refs


def _route_exists(adapter: MapAdapter, path: str) -> bool:
    for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
        try:
            adapter.match(path, method=method)
            return True
        except RequestRedirect:
            return True
        except Exception:
            continue
    return False


def _route_signature(app: Flask) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (
            rule.rule,
            tuple(sorted(method for method in rule.methods if method not in {"HEAD", "OPTIONS"})),
        )
        for rule in app.url_map.iter_rules()
    }


def _frontend_static_refs() -> set[tuple[str, str]]:
    patterns = [
        re.compile(r"url_for\(['\"]static['\"],\s*filename=['\"]([^'\"]+)['\"]"),
        re.compile(r"(?:src|href)=['\"](?:\{\{\s*)?/?static/([^'\"}\s]+)"),
        re.compile(
            r"['\"]/?static/([^'\"]+\.(?:js|css|png|jpg|jpeg|webp|svg|ico|woff2?))['\"]"
        ),
    ]
    paths = [
        *Path("web/templates").rglob("*.html"),
        *Path("web/static").rglob("*.html"),
        *Path("web/static/js").rglob("*.js"),
        *Path("web/static/css").rglob("*.css"),
    ]
    refs: set[tuple[str, str]] = set()
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in patterns:
            for match in pattern.finditer(text):
                ref = match.group(1).split("?", 1)[0]
                if "{{" in ref or "}}" in ref or ref.startswith(("http:", "https:")):
                    continue
                refs.add((str(path), ref))
    return refs


def _frontend_page_refs() -> set[tuple[str, str]]:
    patterns = [
        re.compile(r"(?:href|action)=['\"](/(?!/|api/|static/|#)[^'\"?#\s]*)"),
        re.compile(
            r"(?:location\.href|window\.location(?:\.href)?|window\.open)\s*=\s*['\"](/(?!/|api/|static/|#)[^'\"?#\s]*)"
        ),
        re.compile(r"window\.open\(\s*['\"](/(?!/|api/|static/|#)[^'\"?#\s]*)"),
    ]
    paths = [
        *Path("web/templates").rglob("*.html"),
        *Path("web/static").rglob("*.html"),
        *Path("web/static/js").rglob("*.js"),
        *Path("web/src").rglob("*.ts"),
    ]
    refs: set[tuple[str, str]] = set()
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in patterns:
            for match in pattern.finditer(text):
                ref = match.group(1).rstrip("/") or "/"
                if "{{" in ref or "${" in ref or "<" in ref:
                    continue
                refs.add((str(path), ref))
    return refs


def _frontend_wa_handler_refs() -> set[tuple[str, str]]:
    pattern = re.compile(r"\bWA\.([A-Za-z_$][\w$]*)\s*\(")
    refs: set[tuple[str, str]] = set()
    for path in Path("web/templates").rglob("*.html"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            refs.add((str(path), match.group(1)))
    return refs


def _workspace_wa_method_names() -> set[str]:
    assign_pattern = re.compile(
        r"(?:\bWA|\bwa|window\.WA|\(window as any\)\.WA)\.([A-Za-z_$][\w$]*)\s*="
    )
    export_pattern = re.compile(r"export function ([A-Za-z_$][\w$]*)\s*\(")
    names: set[str] = set()
    for path in Path("web/src").rglob("*.ts"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        names.update(assign_pattern.findall(text))
        names.update(export_pattern.findall(text))
    return names


def _frontend_inline_global_refs() -> set[tuple[str, str]]:
    attr_pattern = re.compile(
        r"\bon(?:click|change|input|submit|keydown|mousedown)\s*=\s*(['\"])(.*?)\1",
        re.S,
    )
    call_pattern = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(")
    ignored = {
        "Array",
        "Boolean",
        "Date",
        "Math",
        "Number",
        "Object",
        "String",
        "alert",
        "catch",
        "clearTimeout",
        "confirm",
        "for",
        "function",
        "if",
        "parseFloat",
        "parseInt",
        "prompt",
        "return",
        "setTimeout",
        "showToast",
        "switch",
        "typeof",
        "while",
    }
    refs: set[tuple[str, str]] = set()
    for root in [Path("web/templates"), Path("web/static")]:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".html", ".js"}:
                continue
            if "node_modules" in path.parts or "build" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for attr_match in attr_pattern.finditer(text):
                handler = attr_match.group(2)
                scrubbed = re.sub(r"(['\"])(?:\\.|(?!\1).)*\1", "''", handler)
                for call_match in call_pattern.finditer(scrubbed):
                    name = call_match.group(1)
                    if name in ignored or name in {"WA", "document", "event", "this", "window"}:
                        continue
                    refs.add((str(path), name))
    return refs


def _frontend_global_function_names() -> set[str]:
    patterns = [
        re.compile(r"\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("),
        re.compile(r"\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="),
        re.compile(r"(?:window|globalThis)\.([A-Za-z_$][\w$]*)\s*="),
        re.compile(r"\((?:window|globalThis)\s+as\s+any\)\.([A-Za-z_$][\w$]*)\s*="),
        re.compile(r"(?:window|globalThis)\[['\"]([A-Za-z_$][\w$]*)['\"]\]\s*="),
        re.compile(r"export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("),
    ]
    names: set[str] = set()
    for root in [Path("web/src"), Path("web/static/js"), Path("web/templates"), Path("web/static")]:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".ts", ".js", ".html"}:
                continue
            if "node_modules" in path.parts or "build" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for pattern in patterns:
                names.update(pattern.findall(text))
    return names


def _reachable_frontend_sources() -> set[Path]:
    source_root = Path("web/src").resolve()
    entrypoints = [
        "shared/auth.ts",
        "bundles/app.ts",
        "bundles/skills-ui.ts",
        "skills/skills-panel.ts",
        "bundles/workspace.ts",
        "bundles/review.ts",
        "skills/skill-marketplace.ts",
        "skills/skill-community.ts",
    ]
    import_pattern = re.compile(
        r"(?:import|export)\s+(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]"
    )
    reachable: set[Path] = set()
    pending = [source_root / entrypoint for entrypoint in entrypoints]

    while pending:
        path = pending.pop().resolve()
        if path in reachable or not path.is_file():
            continue
        reachable.add(path)
        source = path.read_text(encoding="utf-8")
        for specifier in import_pattern.findall(source):
            if not specifier.startswith("."):
                continue
            candidate = (path.parent / specifier).resolve()
            choices = [candidate, candidate.with_suffix(".ts"), candidate / "index.ts"]
            resolved = next((choice for choice in choices if choice.is_file()), None)
            if resolved is not None:
                pending.append(resolved)

    return reachable


@pytest.mark.unit
@pytest.mark.parametrize("app_factory", [_app_from_deferred_loader, _app_from_service_loader])
def test_frontend_exposed_button_routes_are_registered(app_factory):
    adapter = _adapter(app_factory())

    expected_routes = [
        ("GET", "/"),
        ("GET", "/app"),
        ("GET", "/workspace"),
        ("GET", "/workspace-assistant"),
        ("GET", "/mini"),
        ("GET", "/skill-community"),
        ("GET", "/skill-marketplace"),
        ("GET", "/api/token-stats"),
        ("POST", "/api/token-stats/reset"),
        ("GET", "/api/shadow/status"),
        ("GET", "/api/shadow/observations"),
        ("GET", "/api/shadow/memories"),
        ("POST", "/api/shadow/memories"),
        ("DELETE", "/api/shadow/memories/mem_1"),
        ("GET", "/api/shadow/pending"),
        ("POST", "/api/shadow/dismiss/msg_1"),
        ("POST", "/api/shadow/dismiss-all"),
        ("POST", "/api/shadow/toggle"),
        ("POST", "/api/shadow/tick"),
        ("GET", "/api/shadow/open-tasks"),
        ("POST", "/api/shadow/dismiss-task/task_1"),
        ("GET", "/api/shadow/retry-context/task_1"),
        ("GET", "/api/macro/pending"),
        ("POST", "/api/macro/dismiss/"),
        ("POST", "/api/macro/dismiss/suggestion_1"),
        ("POST", "/api/macro/confirm/"),
        ("POST", "/api/macro/confirm/suggestion_1"),
        ("GET", "/api/bg-agent"),
        ("GET", "/api/bg-agent/"),
        ("POST", "/api/bg-agent/submit"),
        ("GET", "/api/bg-agent/list"),
        ("GET", "/api/bg-agent/task_1"),
        ("GET", "/api/bg-agent/task_1/stream"),
        ("POST", "/api/bg-agent/task_1/approve"),
        ("POST", "/api/bg-agent/task_1/reject"),
        ("POST", "/api/bg-agent/task_1/cancel"),
        ("GET", "/api/jobs/triggers"),
        ("POST", "/api/jobs/triggers"),
        ("POST", "/api/jobs/triggers/bootstrap"),
        ("PATCH", "/api/jobs/triggers/trigger_1"),
        ("DELETE", "/api/jobs/triggers/trigger_1"),
        ("POST", "/api/jobs/triggers/trigger_1/fire"),
        ("GET", "/api/memories"),
        ("POST", "/api/memories"),
        ("POST", "/api/memories/import-profile"),
        ("POST", "/api/memories/batch-extract"),
        ("POST", "/api/memory/style-profile"),
        ("GET", "/api/skillmarket"),
        ("GET", "/api/skillmarket/"),
        ("GET", "/api/skillmarket/community/skill/"),
        ("POST", "/api/skillmarket/community/install/"),
        ("POST", "/api/response/rate"),
        ("GET", "/api/auth/status"),
        ("GET", "/api/auth/me"),
        ("POST", "/api/auth/logout"),
        ("GET", "/api/csrf-token"),
        ("GET", "/api/dev/checkpoint-info"),
        ("GET", "/api/v1/workspace/pdf/load_annotations/"),
    ]

    for method, path in expected_routes:
        _assert_route(adapter, method, path)


@pytest.mark.unit
def test_blueprint_loader_wrapper_keeps_route_map_identical():
    deferred_routes = _route_signature(_app_from_deferred_loader())
    service_routes = _route_signature(_app_from_service_loader())

    assert service_routes == deferred_routes


@pytest.mark.unit
@pytest.mark.parametrize("app_factory", [_app_from_deferred_loader, _app_from_service_loader])
def test_frontend_api_string_references_have_backend_routes(app_factory):
    adapter = _adapter(app_factory())
    missing = sorted(
        (source, path)
        for source, path in _frontend_api_refs()
        if not _route_exists(adapter, path)
    )

    assert missing == []


@pytest.mark.unit
@pytest.mark.parametrize("app_factory", [_app_from_deferred_loader, _app_from_service_loader])
def test_frontend_page_links_have_backend_routes(app_factory):
    adapter = _adapter(app_factory())
    missing = sorted(
        (source, path)
        for source, path in _frontend_page_refs()
        if not _route_exists(adapter, path)
    )

    assert missing == []


@pytest.mark.unit
def test_template_wa_handlers_have_workspace_exports():
    methods = _workspace_wa_method_names()
    missing = sorted(
        (source, method)
        for source, method in _frontend_wa_handler_refs()
        if method not in methods
    )

    assert missing == []


@pytest.mark.unit
def test_inline_global_handlers_have_frontend_exports():
    names = _frontend_global_function_names()
    missing = sorted(
        (source, name)
        for source, name in _frontend_inline_global_refs()
        if name not in names
    )

    assert missing == []


@pytest.mark.unit
def test_skills_panel_lazy_loader_installs_global_bridges_before_first_click():
    html = Path("web/templates/index.html").read_text(encoding="utf-8")

    assert "js/build/skills-ui-bundle.js" in html
    assert "js/build/skills-panel-bundle.js" in html
    assert "window.KotoSkillsLoader={load:load}" in html
    assert "['openSkillsPanel','closeSkillsPanel','toggleSkillsPanel']" in html
    assert "window[name]=stubs[name]" in html
    assert "callAfterLoad(name, arguments)" in html
    assert "#navSkillsBtn,#csbToggleBtn,#skillsPanel .close-panel" in html
    assert '[data-action="open-skills"]' in html


@pytest.mark.unit
def test_frontend_static_asset_references_exist():
    missing = sorted(
        (source, ref)
        for source, ref in _frontend_static_refs()
        if not (Path("web/static") / ref).exists()
    )

    assert missing == []


@pytest.mark.unit
def test_all_typescript_sources_are_reachable_from_a_bundle_entrypoint():
    source_root = Path("web/src").resolve()
    all_sources = {path.resolve() for path in source_root.rglob("*.ts")}
    unreachable = sorted(
        path.relative_to(source_root).as_posix()
        for path in all_sources - _reachable_frontend_sources()
    )

    assert unreachable == []


@pytest.mark.unit
def test_retired_frontend_artifacts_stay_removed():
    retired = [
        "web/static/css/inline-extracted.css",
        "web/static/css/workspace-assistant.css",
        "web/static/test-sheets.html",
        "web/static/koto-minimal-tech-preview.html",
        "web/templates/_workspace_model_controls_compact.html",
        "web/src/editors/docx-readview.ts",
        "web/src/workspace/tiptap-types.ts",
    ]

    assert [path for path in retired if Path(path).exists()] == []


@pytest.mark.unit
def test_frontend_button_sources_keep_matching_backend_clusters():
    frontend_sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in [
            "web/src/app/main.ts",
            "web/src/app/marketplace.ts",
            "web/src/app/settings.ts",
            "web/src/skills/skills-panel.ts",
            "web/templates/index.html",
        ]
    )
    job_routes = Path("app/api/job_routes.py").read_text(encoding="utf-8")
    app_blueprints = Path("web/app_blueprints.py").read_text(encoding="utf-8")
    blueprint_loader = Path("web/services/blueprint_loader.py").read_text(encoding="utf-8")

    assert "/api/shadow/" in frontend_sources
    assert "from app.api.shadow_routes import shadow_bp" in app_blueprints
    assert '"web.blueprints.token_stats", "token_stats_bp"' in app_blueprints
    assert "@job_bp.get(\"/triggers\")" in job_routes
    assert "@job_bp.post(\"/triggers/bootstrap\")" in job_routes
    assert "# @job_bp.get(\"/triggers\")" not in job_routes
    assert "register_memory_routes" in app_blueprints
    assert "from web.auth import register_auth_routes" in app_blueprints
    assert "from web.app_http import configure_http_wiring" in app_blueprints
    assert "from app.api.response_routes import response_bp" in app_blueprints
    assert "register_blueprints_deferred" in blueprint_loader
    assert "from app.api.shadow_routes import shadow_bp" not in blueprint_loader
    assert "_WEB_BLUEPRINT_CONFIGS" not in blueprint_loader
