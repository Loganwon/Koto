# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import re
from pathlib import Path

import pytest
from flask import Flask
from werkzeug.routing import MapAdapter, RequestRedirect


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

    app = Flask(__name__)
    app.config["KOTO_OPTIONAL_FEATURES"] = "*"
    app_blueprints.register_blueprints_deferred(app, _NullLogger())
    return app


def _adapter(app: Flask) -> MapAdapter:
    return app.url_map.bind("localhost")


def _assert_route(adapter: MapAdapter, method: str, path: str) -> None:
    try:
        adapter.match(path, method=method)
    except Exception as exc:
        raise AssertionError(f"missing frontend route: {method} {path}") from exc


def _frontend_api_refs(root: Path = Path("web")) -> set[tuple[str, str]]:
    pattern = re.compile(r"['\"](/api/[A-Za-z0-9_./{}?=&:%+-]+)['\"]")
    paths = [
        *root.rglob("*.js"),
        *root.rglob("*.ts"),
        *root.rglob("*.html"),
    ]
    refs: set[tuple[str, str]] = set()
    for path in paths:
        if "node_modules" in path.parts:
            continue
        if path.name.endswith((".test.ts", ".spec.ts", ".test.js", ".spec.js")):
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
            tuple(
                sorted(
                    method
                    for method in rule.methods
                    if method not in {"HEAD", "OPTIONS"}
                )
            ),
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
    publish_pattern = re.compile(r"registerFeatures\(\s*\{(.*?)\}\s*\)", re.S)
    published_name_pattern = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*(?=[:,}]|$)", re.M)
    names: set[str] = set()
    for path in Path("web/src").rglob("*.ts"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        names.update(assign_pattern.findall(text))
        names.update(export_pattern.findall(text))
        for entries in publish_pattern.findall(text):
            names.update(published_name_pattern.findall(entries))
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
                    if name in ignored or name in {
                        "WA",
                        "document",
                        "event",
                        "this",
                        "window",
                    }:
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
    for root in [
        Path("web/src"),
        Path("web/static/js"),
        Path("web/templates"),
        Path("web/static"),
    ]:
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
    build_recipe = Path("web/scripts/build-bundles.mjs").read_text(encoding="utf-8")
    entry_map = re.search(r"(?ms)^const entries = \{(.*?)^\};", build_recipe)
    assert entry_map is not None, "frontend build entry map is missing"
    entrypoints = re.findall(
        r"['\"][^'\"]+['\"]\s*:\s*['\"]src/([^'\"]+\.ts)['\"]",
        entry_map.group(1),
    )
    assert entrypoints, "frontend build entry map has no TypeScript entries"
    # Auth is also loaded as a standalone script, outside the bundle recipe.
    entrypoints.append("shared/auth.ts")
    for entrypoint in entrypoints:
        assert (source_root / entrypoint).is_file(), entrypoint
    import_pattern = re.compile(
        r"(?:import|export)\s*(?:\(|(?:[^'\"]*?\s+from\s+)?)['\"]([^'\"]+)['\"]"
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
def test_api_reference_scan_excludes_test_fixtures_but_keeps_production(tmp_path):
    (tmp_path / "actions.ts").write_text("fetch('/api/real_action');", encoding="utf-8")
    for name in ["actions.test.ts", "actions.spec.ts", "actions.test.js"]:
        (tmp_path / name).write_text("fetch('/api/fake_fixture');", encoding="utf-8")

    assert _frontend_api_refs(tmp_path) == {
        (str(tmp_path / "actions.ts"), "/api/real_action")
    }


@pytest.mark.unit
def test_reachable_sources_follow_declared_lazy_entries_without_hiding_orphans(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    source_root = tmp_path / "web/src"
    (source_root / "bundles").mkdir(parents=True)
    (source_root / "shared").mkdir()
    (tmp_path / "web/scripts").mkdir()
    (tmp_path / "web/scripts/build-bundles.mjs").write_text(
        "const entries = {\n 'lazy-review-bundle': 'src/bundles/review.ts',\n};\n",
        encoding="utf-8",
    )
    (source_root / "bundles/review.ts").write_text(
        "import '../review-actions';", encoding="utf-8"
    )
    (source_root / "review-actions.ts").write_text("export {};", encoding="utf-8")
    (source_root / "orphan.ts").write_text("export {};", encoding="utf-8")
    (source_root / "shared/auth.ts").write_text("export {};", encoding="utf-8")

    assert _reachable_frontend_sources() == {
        source_root / "bundles/review.ts",
        source_root / "review-actions.ts",
        source_root / "shared/auth.ts",
    }


@pytest.mark.unit
@pytest.mark.parametrize("app_factory", [_app_from_deferred_loader])
def test_frontend_exposed_button_routes_are_registered(app_factory):
    adapter = _adapter(app_factory())

    expected_routes = [
        ("GET", "/"),
        ("GET", "/app"),
        ("GET", "/mini"),
        ("GET", "/addons"),
        ("GET", "/api/memories"),
        ("POST", "/api/memories"),
        ("POST", "/api/memories/import-profile"),
        ("POST", "/api/memories/batch-extract"),
        ("POST", "/api/memory/style-profile"),
        ("POST", "/api/response/rate"),
        ("GET", "/api/auth/status"),
        ("GET", "/api/auth/me"),
        ("POST", "/api/auth/logout"),
        ("GET", "/api/csrf-token"),
        ("GET", "/api/v1/workspace/pdf/load_annotations/"),
    ]

    for method, path in expected_routes:
        _assert_route(adapter, method, path)


@pytest.mark.unit
def test_retired_blueprint_loader_wrapper_stays_removed():
    assert not Path("web/services/blueprint_loader.py").exists()


@pytest.mark.unit
@pytest.mark.parametrize("app_factory", [_app_from_deferred_loader])
def test_frontend_api_string_references_have_backend_routes(app_factory):
    adapter = _adapter(app_factory())
    missing = sorted(
        (source, path)
        for source, path in _frontend_api_refs()
        if not _route_exists(adapter, path)
    )

    assert missing == []


@pytest.mark.unit
@pytest.mark.parametrize("app_factory", [_app_from_deferred_loader])
def test_frontend_page_links_have_backend_routes(app_factory):
    adapter = _adapter(app_factory())
    missing = sorted(
        (source, path)
        for source, path in _frontend_page_refs()
        if not _route_exists(adapter, path)
    )

    assert missing == []


@pytest.mark.unit
def test_templates_have_no_window_wa_business_handlers():
    assert _frontend_wa_handler_refs() == set()


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
def test_p3_template_event_routes_are_complete_and_inline_free():
    routed_sources = [
        Path("web/templates/index.html"),
        Path("web/templates/_workspace_close_warn_dialog.html"),
        Path("web/templates/_workspace_docx_color_picker.html"),
        Path("web/templates/_workspace_selection_toolbar.html"),
        Path("web/src/app/template-runtime.ts"),
    ]
    controller = Path("web/src/app/template-event-controller.ts").read_text(
        encoding="utf-8"
    )
    handler_ids = set(re.findall(r'"(h_[A-Za-z0-9_]+)"\s*:', controller))
    references: set[str] = set()
    inline_event_pattern = re.compile(
        r"\bon(?:click|change|input|submit|keydown|keyup|mousedown|mouseup|"
        r"pointerdown|dragover|dragleave|drop|contextmenu)\s*=\s*['\"]",
        re.IGNORECASE,
    )
    for path in routed_sources:
        source = path.read_text(encoding="utf-8")
        assert inline_event_pattern.search(source) is None, path.as_posix()
        references.update(
            re.findall(r'data-koto-event-[\w-]+="(h_[A-Za-z0-9_]+)"', source)
        )

    assert references
    assert sorted(references - handler_ids) == []


@pytest.mark.unit
def test_template_event_routes_resolve_business_actions_through_feature_registry():
    controller_path = Path("web/src/app/template-event-controller.ts")
    controller = controller_path.read_text(encoding="utf-8")
    registered_actions: set[str] = set()
    for path in Path("web/src").rglob("*.ts"):
        if path == controller_path:
            continue
        source = path.read_text(encoding="utf-8")
        registered_actions.update(
            re.findall(r"getFeatureRegistry\(\)\.([A-Za-z_$][\w$]*)\s*=", source)
        )

    bare_calls = sorted(
        name
        for name in registered_actions
        if re.search(rf"(?<![\w.]){re.escape(name)}\s*\(", controller)
    )

    assert registered_actions
    assert bare_calls == []
    assert "LegacyTemplateAction" not in controller
    assert "window." not in controller


@pytest.mark.unit
def test_capability_panel_lazy_loader_installs_registry_bridges_before_first_click():
    html = Path("web/templates/_workspace_asset_scripts.html").read_text(
        encoding="utf-8"
    )
    runtime = Path("web/src/app/template-runtime.ts").read_text(encoding="utf-8")
    app_entry = Path("web/src/bundles/app.ts").read_text(encoding="utf-8")
    build_script = Path("web/scripts/build-bundles.mjs").read_text(encoding="utf-8")

    assert "data-capability-panel-bundle-url" in html
    assert "data-workspace-bundle-url" in html
    assert "'capability-panel-bundle': 'src/addons/capability-panel.ts'" in build_script
    assert "capability-panel" not in app_entry
    assert "marketplace" not in app_entry
    assert "registerFeatures({ loadCapabilityPanelBundle: load })" in runtime
    assert "registerFeatures({ loadWorkspaceBundle: load })" in runtime
    assert "koto:workspace-ready" in runtime
    assert "'openCapabilityPanel'" in runtime
    assert "'closeCapabilityPanel'" in runtime
    assert "'toggleCapabilityPanel'" in runtime
    assert "getFeatureRegistry()[name] = stubs[name]" in runtime
    assert "callAfterLoad(name, args)" in runtime
    assert "#navCapabilityBtn,#capabilityPanel .ui-close-button" in runtime
    assert '[data-action="open-addons"]' in runtime


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
    all_sources = {
        path.resolve()
        for path in source_root.rglob("*.ts")
        if not path.name.endswith(".test.ts")
    }
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
        "web/src/bundles/skills-ui.ts",
        "web/src/skills/skill-marketplace.ts",
        "web/src/skills/skill-community.ts",
        "web/src/skills/skill-ui-extensions.ts",
        "web/src/skills/skill-ui.ts",
        "web/src/app/marketplace.ts",
        "web/src/extras/tarot-picker.ts",
        "web/src/skills/skills-panel.ts",
    ]

    assert [path for path in retired if Path(path).exists()] == []


@pytest.mark.unit
def test_frontend_button_sources_keep_matching_backend_clusters():
    frontend_sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in [
            "web/src/app/main.ts",
            "web/src/app/settings.ts",
            "web/src/addons/capability-panel.ts",
            "web/templates/index.html",
        ]
    )
    job_routes = Path("app/api/job_routes.py").read_text(encoding="utf-8")
    app_runtime = Path("web/app_runtime.py").read_text(encoding="utf-8")
    app_blueprints = Path("web/app_blueprints.py").read_text(encoding="utf-8")

    assert "/api/shadow/" not in frontend_sources
    assert "app.api.shadow_routes" not in app_blueprints
    assert "web.blueprints.token_stats" not in app_blueprints
    assert not Path("web/blueprints/token_stats.py").exists()
    assert '"/triggers"' not in job_routes
    assert "get_trigger_registry" not in app_runtime
    assert "register_memory_routes" in app_blueprints
    assert 'importlib.import_module("web.blueprints.auth")' in app_blueprints
    assert "from web.app_http import configure_http_wiring" in app_blueprints
    assert '"app.api.response_routes", "response_bp", "ResponseAPI"' in app_blueprints
    assert not Path("web/services/blueprint_loader.py").exists()
