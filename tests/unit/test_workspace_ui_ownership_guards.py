# -*- coding: utf-8 -*-
"""Regression guards for workspace UI ownership boundaries."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_latency_detail_stays_owned_by_the_activity_rail() -> None:
    html = _read("web/templates/index.html")
    settings = _read("web/src/app/settings.ts")
    workspace_css = _read("web/static/css/workspace.css")

    assert 'id="latencyDetail"' in html
    assert "wa-left-latency-slot" not in html
    assert "appendChild(detail)" not in settings
    assert "The status detail belongs to the activity rail" in settings
    assert ".koto-activity-bar .latency-detail.open" in workspace_css


def test_legacy_drawer_rules_cannot_override_the_unified_workspace() -> None:
    css = _read("web/static/css/style.css")
    workspace_css = _read("web/static/css/workspace.css")

    assert ".app-shell:not(.koto-unified-workspace) .nav-rail {" in css
    assert "\n    .nav-rail { position: fixed; left: -320px;" not in css
    assert ".app-shell.koto-unified-workspace #sideNav" in workspace_css
    assert "position: relative;" in workspace_css


def test_workspace_compatibility_exports_use_the_single_api_boundary() -> None:
    state = _read("web/src/workspace/state.ts")
    results = _read("web/src/workspace/results.ts")

    assert "const wa = getWorkspaceApi();" in state
    assert "(window as any).WA = wa;" not in state
    assert (
        "publishWorkspaceApi({ renderArtifactResult, loadBackgroundArtifactResult });"
        in results
    )
    assert "publishWorkspaceApi({ createWorkspaceAiResultsRuntime });" in results
