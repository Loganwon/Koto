# -*- coding: utf-8 -*-
"""Regression guards for workspace UI ownership boundaries."""

from pathlib import Path

from tests.source_graph import read_frontend_partitions

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    if Path(relative_path).suffix in {".ts", ".js", ".css"}:
        return read_frontend_partitions(relative_path)
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_latency_detail_stays_owned_by_the_activity_rail() -> None:
    html = _read("web/templates/_workspace_sidebar.html")
    settings = _read("web/src/app/settings.ts")
    workspace_css = _read("web/static/css/workspace-shell.css")

    assert 'id="latencyDetail"' in html
    assert "wa-left-latency-slot" not in html
    assert "appendChild(detail)" not in settings
    assert "The status detail belongs to the task sidebar" in settings
    assert ".koto-sidebar .latency-detail.open" in workspace_css


def test_legacy_drawer_rules_cannot_override_the_unified_workspace() -> None:
    css = _read("web/static/css/style.css")
    workspace_css = _read("web/static/css/workspace-shell.css")

    assert ".app-shell:not(.koto-unified-workspace) .nav-rail {" in css
    assert "\n    .nav-rail { position: fixed; left: -320px;" not in css
    assert ".app-shell.koto-unified-workspace #sideNav" in workspace_css
    assert "position: relative;" in workspace_css


def test_workspace_compatibility_exports_use_the_single_api_boundary() -> None:
    state = _read("web/src/workspace/state.ts")
    results = _read("web/src/workspace/results.ts")

    assert "const wa = getFeatureRegistry();" in state
    assert "(window as any).WA = wa;" not in state
    assert "registerFeatures({ renderArtifactResult });" in results
    assert "export function createWorkspaceAiResultsRuntime(" in results
    assert "registerFeatures({ createWorkspaceAiResultsRuntime })" not in results
