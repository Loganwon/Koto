from __future__ import annotations

import ast
from pathlib import Path

import pytest
from flask import Flask

from app.api.plugin_protocol_routes import plugin_protocol_bp


@pytest.fixture()
def protocol_client(tmp_path):
    from app.core.agent.addons import (
        AddonRegistrationStore,
        set_addon_runtime,
        set_addon_store,
    )

    set_addon_store(AddonRegistrationStore(tmp_path / "addons.json"))
    set_addon_runtime(None)
    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(plugin_protocol_bp)
    yield app.test_client()
    set_addon_store(None)
    set_addon_runtime(None)


def test_plugin_protocol_frontend_contract_exposes_registration_boundary(
    protocol_client,
):
    status = protocol_client.get("/api/plugin-protocol").get_json()
    assert status["success"] is True
    assert status["protocol"]["status"] == "contract_ready"
    assert status["runtime"]["execution"] is True
    assert status["runtime"]["task_routing"] is True
    assert status["runtime"]["registration"] is True
    assert status["runtime"]["enabled_transports"] == ["in_process"]
    assert set(status["supported"]["contribution_kinds"]) == {"tool", "retriever"}
    assert set(status["supported"]["schema_transports"]) == {
        "http",
        "in_process",
        "mcp",
    }
    assert status["supported"]["runtime_enabled_transports"] == ["in_process"]
    assert "admitted_plugins" not in status["runtime"]

    catalog = protocol_client.get("/api/plugin-protocol/catalog").get_json()
    assert catalog["addons"] == []
    assert catalog["total"] == 0
    assert "plugins" not in catalog


def test_plugin_protocol_validates_without_installing(protocol_client):
    example = protocol_client.get("/api/plugin-protocol/example").get_json()["manifest"]
    response = protocol_client.post(
        "/api/plugin-protocol/validate", json={"manifest": example}
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["valid"] is True
    assert data["next_step"] == "manifest_valid_only"
    assert data["summary"]["risk"]["tenant_isolation"] is True
    assert len(data["digest"]) == 64


def test_plugin_protocol_returns_actionable_validation_error(protocol_client):
    example = protocol_client.get("/api/plugin-protocol/example").get_json()["manifest"]
    example["runtime"]["entrypoint"] = "http://unsafe.example/plugin"
    response = protocol_client.post(
        "/api/plugin-protocol/validate", json={"manifest": example}
    )
    assert response.status_code == 422
    assert response.get_json()["stage"] == "manifest_validation"


def test_registration_is_persisted_disabled_and_enable_fails_closed_without_factory(
    protocol_client,
):
    example = protocol_client.get("/api/plugin-protocol/example").get_json()
    response = protocol_client.post(
        "/api/plugin-protocol/registrations",
        json=example["registration"],
    )

    assert response.status_code == 201
    addon = response.get_json()["addon"]
    assert addon["enabled"] is False
    assert addon["state"] == "registered"

    enable = protocol_client.put(
        f"/api/plugin-protocol/registrations/{addon['addon_id']}/enabled",
        json={"enabled": True},
    )
    assert enable.status_code == 409
    assert enable.get_json()["stage"] == "runtime_admission"


def test_cloud_registration_requires_operator_token(protocol_client, monkeypatch):
    monkeypatch.setenv("KOTO_AUTH_ENABLED", "true")
    monkeypatch.setenv("KOTO_ADMIN_TOKEN", "operator-secret")
    registration = protocol_client.get("/api/plugin-protocol/example").get_json()[
        "registration"
    ]

    denied = protocol_client.post(
        "/api/plugin-protocol/registrations", json=registration
    )
    allowed = protocol_client.post(
        "/api/plugin-protocol/registrations",
        json=registration,
        headers={"X-Admin-Token": "operator-secret"},
    )

    assert denied.status_code == 403
    assert allowed.status_code == 201


def test_retired_skill_runtime_and_product_surfaces_are_physically_removed():
    root = Path(__file__).resolve().parents[2]
    removed = (
        root / "app/api/skill_routes.py",
        root / "app/api/skill_marketplace_routes.py",
        root / "web/templates/skill_marketplace.html",
        root / "web/templates/skill_community.html",
        root / "web/src/app/marketplace.ts",
        root / "web/static/js/build/skills-ui-bundle.js",
        root / "web/static/js/build/skills-panel-bundle.js",
    )
    assert not [str(path.relative_to(root)) for path in removed if path.exists()]
    legacy_package = root / "app/core/skills"
    if legacy_package.exists():
        assert not list(legacy_package.glob("*.py"))


def test_production_python_has_no_legacy_skill_imports():
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for base in (root / "app", root / "web", root / "launcher"):
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "app.core.skills" in text:
                offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_addon_and_protocol_layers_cannot_import_web_or_legacy_skills():
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for package in (
        root / "app/core/agent/addons",
        root / "app/core/agent/plugin_protocol",
    ):
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                for module in modules:
                    if (
                        module == "web"
                        or module.startswith("web.")
                        or module.startswith("app.core.skills")
                    ):
                        offenders.append(f"{path.relative_to(root)} imports {module}")
    assert offenders == []


def test_legacy_skill_http_runtime_is_removed():
    root = Path(__file__).resolve().parents[2]
    editor_ai = (root / "web/blueprints/editor_ai.py").read_text(encoding="utf-8")
    assert "/api/editor/ai/skill-list" not in editor_ai
    assert "skill_runtime_retired" not in editor_ai


def test_main_capability_panel_is_addon_owned():
    root = Path(__file__).resolve().parents[2]
    index = (root / "web/templates/index.html").read_text(encoding="utf-8")
    panel = (root / "web/src/addons/addon-panel.ts").read_text(encoding="utf-8")
    center = (root / "web/src/addons/addon-center.ts").read_text(encoding="utf-8")
    controller = (root / "web/src/addons/capability-panel.ts").read_text(
        encoding="utf-8"
    )
    assets = (root / "web/templates/_workspace_asset_scripts.html").read_text(
        encoding="utf-8"
    )

    assert 'id="addonPanelSurface"' in index
    assert 'href="/addons"' in index
    assert "'/api/plugin-protocol'" in panel
    assert "'/api/plugin-protocol/catalog'" in panel
    assert "import './addon-panel';" in controller
    assert "'/api/plugin-protocol/registrations'" in center
    assert "registerAddon" in center
    assert 'id="registration-input"' in (
        root / "web/templates/addon_center.html"
    ).read_text(encoding="utf-8")
    assert "data-capability-panel-bundle-url" in assets
    assert "skills-ui-bundle" not in assets


def test_agent_tool_profiles_have_no_skill_adapter_path():
    root = Path(__file__).resolve().parents[2]
    source = (root / "app/core/agent/tool_profiles.py").read_text(encoding="utf-8")
    assert "include_skills" not in source
    assert "SkillToolAdapter" not in source
    assert "quarantined_skills" not in source
    assert "include_addons=True" in source
    assert "include_mcp" not in source
    assert "include_user_tools" not in source
    assert "legacy_full" not in source
    assert "legacy_light" not in source

    factory = (root / "app/core/agent/factory.py").read_text(encoding="utf-8")
    assert "full: bool" not in factory
    assert 'profile: str = "core"' in factory


def test_host_builtins_are_not_stored_in_a_plugin_namespace():
    root = Path(__file__).resolve().parents[2]
    profiles = (root / "app/core/agent/tool_profiles.py").read_text(encoding="utf-8")
    builtin_package = root / "app/core/agent/toolkits/builtin"

    assert not (root / "app/core/agent/plugins").exists()
    assert builtin_package.is_dir()
    assert (builtin_package / "basic_tools_plugin.py").is_file()
    assert "app.core.agent.plugins" not in profiles
    assert "app.core.agent.toolkits.builtin" in profiles
    assert "class BuiltinToolDescriptor" in profiles
    assert "loaded_builtins" in profiles


def test_addon_file_matching_normalizes_office_mime_types_and_attachments():
    from web.services.chat_stream.orchestrator import _addon_file_types

    result = _addon_file_types(
        {
            "file_type": "application/pdf",
            "file_path": "C:/work/report.docx",
            "attached_files": [{"name": "ledger.xlsx"}, "terms.PDF"],
        },
        "text/csv",
        "C:/work/slides.pptx",
    )
    assert result == ("csv", "pptx", "pdf", "docx", "xlsx")


def test_addon_data_classification_cannot_be_downgraded_by_client():
    from web.services.chat_stream.orchestrator import _addon_data_classification

    assert _addon_data_classification("public") == "internal"
    assert _addon_data_classification("internal", ("pdf",)) == "confidential"
    assert _addon_data_classification("restricted", ("pdf",)) == "restricted"
