from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import scripts.audit_code_baseline as baseline


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def test_todo_scan_uses_filtered_production_code_roots(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "web" / "static" / "vendor").mkdir(parents=True)
    (tmp_path / "web" / "static" / "js" / "build").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()

    (tmp_path / "app" / "live.py").write_text("# TODO: real\n", encoding="utf-8")
    (tmp_path / "src" / "tool.py").write_text("# FIXME: real\n", encoding="utf-8")
    (tmp_path / "tests" / "test_live.py").write_text(
        "# TODO: ignored\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "note.md").write_text("TODO: ignored\n", encoding="utf-8")
    (tmp_path / "web" / "static" / "vendor" / "lib.js").write_text(
        "// TODO: ignored\n", encoding="utf-8"
    )
    (tmp_path / "web" / "static" / "js" / "build" / "bundle.js").write_text(
        "// FIXME: ignored\n", encoding="utf-8"
    )

    monkeypatch.setattr(baseline, "ROOT", tmp_path)

    matches = baseline._find_todos()

    assert "app/live.py:1: # TODO: real" in matches
    assert "src/tool.py:1: # FIXME: real" in matches
    assert not any("tests/" in match for match in matches)
    assert not any("docs/" in match for match in matches)
    assert not any("static/vendor" in match for match in matches)
    assert not any("static/js/build" in match for match in matches)


def test_collect_baseline_keeps_audit_contract_fields(
    tmp_path: Path, monkeypatch
) -> None:
    file_task_runtime = "File" + "TaskRuntime"
    kernel_agent = "Kernel" + "Agent"

    (tmp_path / "app" / "core" / "agent").mkdir(parents=True)
    (tmp_path / "web" / "static" / "js" / "build").mkdir(parents=True)
    (tmp_path / "web" / "static" / "univer-dist" / "assets").mkdir(parents=True)
    (tmp_path / "web" / "static" / "vendor").mkdir(parents=True)
    (tmp_path / "web" / "node_modules" / "pkg").mkdir(parents=True)

    (tmp_path / "web" / "app.py").write_text(
        "def chat():\n    return 'ok'\n\nclass KotoBrain:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "core" / "agent" / "runtime.py").write_text(
        f"class {file_task_runtime}:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "large_service.py").write_text(
        "\n".join(["# service"] * 1500),
        encoding="utf-8",
    )
    (tmp_path / "web" / "large_panel.ts").write_text(
        "\n".join(["// panel"] * 2000),
        encoding="utf-8",
    )
    (tmp_path / "web" / "static" / "js" / "build" / "ignored-large.js").write_text(
        "\n".join(["// build"] * 3000),
        encoding="utf-8",
    )
    (tmp_path / "app" / "core" / "agent" / "kernel_agent.py").write_text(
        f"class {kernel_agent}:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "web" / "static" / "js" / "build" / "workspace-bundle.js").write_text(
        "workspace",
        encoding="utf-8",
    )
    (tmp_path / "web" / "static" / "tiptap-docx-bundle.js").write_text(
        "docx",
        encoding="utf-8",
    )
    (
        tmp_path / "web" / "static" / "univer-dist" / "assets" / "sheets-main.js"
    ).write_text(
        "sheets",
        encoding="utf-8",
    )
    (tmp_path / "web" / "static" / "vendor" / "lib.js").write_text(
        "vendor",
        encoding="utf-8",
    )
    (tmp_path / "web" / "node_modules" / "pkg" / "index.js").write_text(
        "module",
        encoding="utf-8",
    )

    monkeypatch.setattr(baseline, "ROOT", tmp_path)

    result = baseline.collect_baseline()

    assert result["web_app_lines"] == 5
    assert result["agent_py_top_level"] == 2
    assert result["agent_py_recursive"] == 2
    assert result["bundles_bytes"]["web/static/js/build/workspace-bundle.js"] == 9
    assert result["web_static_vendor_bytes"] == 6
    assert result["web_node_modules_bytes"] == 6
    assert result["large_file_summary"] == {
        "over_1500_count": 2,
        "over_1500_lines": 3500,
        "over_2000_count": 1,
        "over_2000_lines": 2000,
    }
    assert result["large_production_files"][:2] == [
        {"path": "web/large_panel.ts", "lines": 2000},
        {"path": "app/large_service.py", "lines": 1500},
    ]
    assert not any(
        item["path"] == "web/static/js/build/ignored-large.js"
        for item in result["large_production_files"]
    )
    assert result["web_app_top_level_exports"] == ["chat", "KotoBrain"]
    assert (
        "app/core/agent/runtime.py"
        in result["agent_entrypoint_hits"][file_task_runtime]
    )
    assert (
        "app/core/agent/kernel_agent.py"
        in result["agent_entrypoint_hits"][kernel_agent]
    )
    assert "deleted_agent_entrypoint_hits" in result
    assert all(not files for files in result["deleted_agent_entrypoint_hits"].values())
    assert (
        "app/core/agent/kernel_agent.py"
        in result["agent_production_entrypoint_hits"][kernel_agent]
    )
    assert "frontend_runtime_debt" in result
    assert "architecture_budget_status" in result
    assert "compatibility_debt" in result
    assert "feature_ownership_validation_errors" in result
    assert "route_ownership_validation_errors" in result


def test_frontend_runtime_debt_counts_inline_and_global_boundaries(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "web" / "templates").mkdir(parents=True)
    (tmp_path / "web" / "src").mkdir(parents=True)
    (tmp_path / "web" / "templates" / "index.html").write_text(
        """
        <button onclick="WA.openFile()">open</button>
        <input oninput="WA.filterFiles(this.value)">
        <script>window.inlineBoot = true;</script>
        <script src="/static/js/build/app.js"></script>
        """,
        encoding="utf-8",
    )
    (tmp_path / "web" / "src" / "runtime.ts").write_text(
        """
        (window as any).state = {};
        window.LegacyAction = () => {};
        publishWorkspaceApi({ openFile() {} });
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "ROOT", tmp_path)

    debt = baseline._frontend_runtime_debt()

    assert debt["inline_script_tags"] == 1
    assert debt["external_script_tags"] == 1
    assert debt["inline_event_handlers"] == 2
    assert debt["inline_wa_event_handlers"] == 2
    assert debt["inline_wa_methods"] == ["filterFiles", "openFile"]
    assert debt["window_global_assignments"] == 2
    assert (
        baseline.WINDOW_ASSIGNMENT_RE.search(
            "if ((window as any).state === undefined) throw new Error('missing');"
        )
        is None
    )
    assert debt["window_state_writes"] == 1
    assert debt["publish_workspace_api_calls"] == 1


def test_compatibility_debt_validation_requires_retirement_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "web").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "web" / "compat.ts").write_text("export {};", encoding="utf-8")
    (tmp_path / "tests" / "test_compat.py").write_text("", encoding="utf-8")
    _write_json(
        tmp_path / baseline.COMPATIBILITY_DEBT_PATH,
        {
            "schema_version": 1,
            "entries": [
                {
                    "id": "frontend.compat",
                    "category": "frontend-runtime",
                    "owner": "frontend-platform",
                    "paths": ["web/compat.ts"],
                    "callers": ["app"],
                    "reason": "migration",
                    "replacement": "typed registry",
                    "target_phase": "P3",
                    "remove_by": "2030-01-01",
                    "delete_when": "callers are zero",
                    "tests": ["tests/test_compat.py"],
                }
            ],
        },
    )
    monkeypatch.setattr(baseline, "ROOT", tmp_path)

    assert baseline._validate_compatibility_debt(dt.date(2029, 1, 1)) == []
    assert baseline._validate_compatibility_debt(dt.date(2030, 1, 2)) == [
        "compatibility debt is overdue: frontend.compat"
    ]


def test_feature_ownership_validation_requires_real_owners_and_tests(
    tmp_path: Path, monkeypatch
) -> None:
    for directory in ("config", "web", "app", "tests"):
        (tmp_path / directory).mkdir()
    (tmp_path / "web" / "feature.ts").write_text("export {};", encoding="utf-8")
    (tmp_path / "app" / "feature.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "test_feature.py").write_text("", encoding="utf-8")
    _write_json(
        tmp_path / baseline.FEATURE_OWNERSHIP_PATH,
        {
            "schema_version": 1,
            "features": [
                {
                    "id": "feature.one",
                    "release_status": "beta",
                    "frontend_owners": ["web/feature.ts"],
                    "backend_owners": ["app/feature.py"],
                    "entrypoints": ["POST /feature"],
                    "tests": ["tests/test_feature.py"],
                    "acceptance": ["returns a real result"],
                    "known_gaps": ["browser coverage pending"],
                }
            ],
        },
    )
    monkeypatch.setattr(baseline, "ROOT", tmp_path)

    assert baseline._validate_feature_ownership() == []


def test_route_ownership_validation_rejects_missing_owner(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "config").mkdir()
    _write_json(
        tmp_path / baseline.ROUTE_OWNERSHIP_PATH,
        {
            "schema_version": 1,
            "families": {
                "chat": {
                    "feature": "chat.primary",
                    "tier": "core",
                    "owner": "web/blueprints/chat.py",
                }
            },
        },
    )
    monkeypatch.setattr(baseline, "ROOT", tmp_path)

    assert baseline._validate_route_ownership() == [
        "families.chat.owner missing: web/blueprints/chat.py"
    ]


def test_current_architecture_debt_stays_within_ratchet() -> None:
    status = baseline._architecture_budget_status()

    expected_metrics = {
        "inline_script_tags",
        "external_script_tags",
        "inline_event_handlers",
        "product_template_inline_event_handlers",
        "inline_wa_event_handlers",
        "inline_wa_method_count",
        "window_global_assignments",
        "unapproved_window_global_assignment_count",
        "generated_inline_event_handlers",
        "window_state_writes",
        "publish_workspace_api_calls",
        "frontend_source_files_over_1000_count",
        "over_1500_count",
        "over_1500_lines",
        "over_2000_count",
        "over_2000_lines",
    }
    assert set(status) == expected_metrics
    assert {name: item for name, item in status.items() if item["over_budget"]} == {}

    initial_p0_ceilings = {
        "inline_script_tags": 11,
        "external_script_tags": 3,
        "inline_event_handlers": 406,
        "inline_wa_event_handlers": 174,
        "inline_wa_method_count": 99,
        "window_global_assignments": 508,
        "window_state_writes": 1,
        "publish_workspace_api_calls": 26,
        "frontend_source_files_over_1000_count": 11,
        "over_1500_count": 33,
        "over_1500_lines": 84985,
        "over_2000_count": 18,
        "over_2000_lines": 59838,
    }
    configured = baseline._load_json_object(baseline.ARCHITECTURE_BUDGETS_PATH)[
        "budgets"
    ]
    assert {
        metric: configured[metric]
        for metric, ceiling in initial_p0_ceilings.items()
        if configured[metric] > ceiling
    } == {}


def test_current_governance_manifests_are_complete_and_not_overdue() -> None:
    assert baseline._validate_compatibility_debt() == []
    assert baseline._validate_feature_ownership() == []
    assert baseline._validate_route_ownership() == []

    feature_data = baseline._load_json_object(baseline.FEATURE_OWNERSHIP_PATH)
    feature_ids = {feature["id"] for feature in feature_data["features"]}
    assert {
        "desktop.startup",
        "settings.model-runtime",
        "chat.primary",
        "workspace.file-open-save",
        "docx.edit-review",
        "xlsx.edit",
        "pptx.edit",
        "pdf.view-annotate",
        "pdf.page-operations",
        "pdf.convert",
        "pdf.remove-watermark",
        "file-ai.task-stream",
    } <= feature_ids

    pdf_features = [
        feature
        for feature in feature_data["features"]
        if feature["id"].startswith("pdf.")
    ]
    assert pdf_features
    assert {feature["release_status"] for feature in pdf_features} == {"stable"}


def test_release_gate_runs_architecture_debt_governance() -> None:
    release_gate = (baseline.ROOT / "scripts" / "run_release_gate.ps1").read_text(
        encoding="utf-8"
    )

    assert "tests/unit/test_audit_code_baseline.py" in release_gate


def test_ai_assistant_suite_nodes_resolve_to_current_tests() -> None:
    from scripts.run_ai_assistant_flow_tests import SUITES

    missing = []
    for suite_name, suite in SUITES.items():
        for node in suite["nodes"]:
            path_text = node.split("::", 1)[0]
            if not (baseline.ROOT / path_text).is_file():
                missing.append(f"{suite_name}: {path_text}")

    assert missing == []


def test_current_agent_entrypoint_scan_keeps_deleted_loop_out() -> None:
    production_hits = baseline._agent_production_entrypoint_hits()
    deleted_hits = baseline._deleted_agent_entrypoint_hits()

    assert all(not files for files in deleted_hits.values())
    assert "app/core/services/file_task_stream.py" in production_hits["FileTaskRuntime"]
    assert "app/core/agent/factory.py" in production_hits["KernelAgent"]


def test_governance_failures_reject_missing_budgets_and_invalid_manifests() -> None:
    result = {
        "architecture_budget_status": {},
        "compatibility_debt": {"validation_errors": ["invalid debt ledger"]},
        "feature_ownership_validation_errors": ["missing owner"],
        "route_ownership_validation_errors": ["missing route owner"],
        "deleted_agent_entrypoint_hits": {"retired": ["app/retired.py"]},
    }

    assert baseline._governance_failures(result) == [
        "architecture debt budgets are missing or empty",
        "invalid debt ledger",
        "missing owner",
        "missing route owner",
        "retired Agent entrypoint returned: retired",
    ]


def test_retired_registry_and_workflow_owners_stay_deleted() -> None:
    root = baseline.ROOT

    assert not (root / "app/core/plugin_protocol/registry.py").exists()
    tool_package = (root / "app/core/agent/tools/__init__.py").read_text(
        encoding="utf-8"
    )
    assert "class ToolRegistry" not in tool_package
    assert "ToolRegistry.register" not in tool_package
    assert list((root / "config/workflows").glob("*.json")) == []
    for path in (
        "web/document_batch_annotator.py",
        "app/core/services/document_batch_annotator.py",
        "app/core/services/document_direct_edit.py",
    ):
        assert not (root / path).exists()


def test_asset_budget_status_reports_files_and_directories(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "web" / "static" / "js" / "build").mkdir(parents=True)
    (tmp_path / "web" / "static" / "vendor" / "lib").mkdir(parents=True)
    (tmp_path / "web" / "static" / "js" / "build" / "workspace-bundle.js").write_text(
        "bundle",
        encoding="utf-8",
    )
    (tmp_path / "web" / "static" / "vendor" / "lib" / "asset.js").write_text(
        "vendor-assets",
        encoding="utf-8",
    )
    (tmp_path / "config" / "frontend_asset_budgets.json").write_text(
        (
            "{\n"
            '  "budgets": {\n'
            '    "web/static/js/build/workspace-bundle.js": 8,\n'
            '    "web/static/vendor": 10\n'
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(baseline, "ROOT", tmp_path)

    status = baseline._asset_budget_status()

    bundle = status["web/static/js/build/workspace-bundle.js"]
    vendor = status["web/static/vendor"]
    assert bundle == {
        "size": 6,
        "budget": 8,
        "remaining": 2,
        "over_budget": False,
    }
    assert vendor == {
        "size": 13,
        "budget": 10,
        "remaining": -3,
        "over_budget": True,
    }


def test_current_frontend_assets_stay_within_budget() -> None:
    status = baseline._asset_budget_status()

    expected_assets = {
        "web/static/univer-dist/assets/sheets-main.js",
        "web/static/js/build/workspace-bundle.js",
        "web/static/js/tiptap-docx-bundle.js",
        "web/static/vendor",
    }
    assert set(status) == expected_assets
    assert {rel: item for rel, item in status.items() if item["over_budget"]} == {}
    assert status["web/static/vendor"]["budget"] <= 6_800_000


def test_vendor_reference_graph_tracks_package_refs(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "web" / "static" / "vendor" / "mermaid" / "10.9.0").mkdir(parents=True)
    (tmp_path / "web" / "static" / "vendor" / "react").mkdir(parents=True)
    (tmp_path / "web" / "templates").mkdir(parents=True)
    (tmp_path / "web" / "src").mkdir(parents=True)
    (
        tmp_path / "web" / "static" / "vendor" / "mermaid" / "10.9.0" / "mermaid.min.js"
    ).write_text(
        "mermaid",
        encoding="utf-8",
    )
    (
        tmp_path / "web" / "static" / "vendor" / "react" / "react.production.min.js"
    ).write_text(
        "react",
        encoding="utf-8",
    )
    (tmp_path / "web" / "static" / "vendor" / "split.min.js").write_text(
        "split",
        encoding="utf-8",
    )
    (tmp_path / "web" / "templates" / "index.html").write_text(
        '<script src="/static/vendor/split.min.js"></script>\n',
        encoding="utf-8",
    )
    (tmp_path / "web" / "src" / "chart.ts").write_text(
        "script.src = '/static/vendor/mermaid/10.9.0/mermaid.min.js';\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(baseline, "ROOT", tmp_path)

    graph = baseline._vendor_reference_graph()

    assert graph["mermaid"]["referenced"] is True
    assert graph["mermaid"]["reference_files"] == ["web/src/chart.ts"]
    assert graph["split.min.js"]["referenced"] is True
    assert graph["split.min.js"]["reference_files"] == ["web/templates/index.html"]
    assert graph["react"]["referenced"] is False
    assert graph["react"]["reference_files"] == []


def test_retired_vendor_bundles_do_not_return() -> None:
    graph = baseline._vendor_reference_graph()

    for package in ("floating-ui", "react", "rxjs", "univer"):
        assert package not in graph
        assert not (baseline.ROOT / "web" / "static" / "vendor" / package).exists()


def test_retired_vendor_download_script_stays_deleted() -> None:
    assert not (baseline.ROOT / "scripts" / "download_vendors.py").exists()
