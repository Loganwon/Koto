from __future__ import annotations

from pathlib import Path

import scripts.audit_code_baseline as baseline


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
    unified_agent = "Unified" + "Agent"

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
    (tmp_path / "app" / "core" / "agent" / "unified_agent.py").write_text(
        f"class {unified_agent}:\n    pass\n",
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
    (tmp_path / "web" / "static" / "univer-dist" / "assets" / "sheets-main.js").write_text(
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
    assert "app/core/agent/runtime.py" in result["agent_entrypoint_hits"][file_task_runtime]
    assert "app/core/agent/unified_agent.py" in result["agent_entrypoint_hits"][unified_agent]
    assert "deleted_agent_entrypoint_hits" in result
    assert all(not files for files in result["deleted_agent_entrypoint_hits"].values())
    assert (
        "app/core/agent/unified_agent.py"
        in result["agent_production_entrypoint_hits"][unified_agent]
    )


def test_current_agent_entrypoint_scan_keeps_deleted_loop_out() -> None:
    production_hits = baseline._agent_production_entrypoint_hits()
    deleted_hits = baseline._deleted_agent_entrypoint_hits()

    assert all(not files for files in deleted_hits.values())
    assert "web/file_task_stream.py" in production_hits["FileTaskRuntime"]
    assert "web/services/chat_stream/agent_handler.py" in production_hits["LangGraphAgent"]
    assert "app/api/agent_routes.py" in production_hits["UnifiedAgent"]


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
    assert {
        rel: item for rel, item in status.items() if item["over_budget"]
    } == {}
    assert status["web/static/vendor"]["budget"] <= 6_800_000


def test_vendor_reference_graph_tracks_package_refs(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "web" / "static" / "vendor" / "mermaid" / "10.9.0").mkdir(parents=True)
    (tmp_path / "web" / "static" / "vendor" / "react").mkdir(parents=True)
    (tmp_path / "web" / "templates").mkdir(parents=True)
    (tmp_path / "web" / "src").mkdir(parents=True)
    (tmp_path / "web" / "static" / "vendor" / "mermaid" / "10.9.0" / "mermaid.min.js").write_text(
        "mermaid",
        encoding="utf-8",
    )
    (tmp_path / "web" / "static" / "vendor" / "react" / "react.production.min.js").write_text(
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


def test_vendor_download_script_matches_current_static_references() -> None:
    source = (baseline.ROOT / "scripts" / "download_vendors.py").read_text(
        encoding="utf-8"
    )

    assert "tailwindcss/tailwind-play-cdn.js" in source
    assert "pdfjs-dist/3.11.174/build/pdf.min.js" in source
    assert "pdfjs-dist/3.11.174/build/pdf.worker.min.js" in source

    retired_tokens = [
        "react/react.production.min.js",
        "react/react-dom.production.min.js",
        "rxjs/rxjs.umd.min.js",
        "floating-ui/floating-ui.core.umd.min.js",
        "floating-ui/floating-ui.dom.umd.min.js",
        "tailwindcss/tailwind.min.css",
        "pdfjs/pdf.min.mjs",
        "pdfjs/pdf.worker.min.mjs",
    ]
    for token in retired_tokens:
        assert token not in source
