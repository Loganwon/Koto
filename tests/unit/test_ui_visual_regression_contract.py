from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "ui_visual_regression.py"
SPEC = importlib.util.spec_from_file_location("ui_visual_regression", SCRIPT_PATH)
assert SPEC and SPEC.loader
visual = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = visual
SPEC.loader.exec_module(visual)


def test_full_visual_matrix_covers_all_zoom_dpr_viewport_and_editor_dimensions():
    cases = visual.full_visual_cases()
    visual.validate_matrix_contract(cases, full=True)

    assert set(case.zoom_pct for case in cases) == set(visual.ZOOM_PCTS)
    assert set(case.dpr for case in cases) == set(visual.DPRS)
    assert set(case.viewport_name for case in cases) == set(visual.VIEWPORTS)
    assert set(case.surface for case in cases) == set(visual.SURFACES)
    assert len(visual.geometry_cases("full")) == 204


def test_smoke_matrix_keeps_boundary_zooms_and_every_editor():
    cases = visual.smoke_visual_cases()
    visual.validate_matrix_contract(cases, full=False)

    assert {70, 100, 125, 150}.issubset({case.zoom_pct for case in cases})
    assert len(cases) == 12
    assert {case.key for case in cases}.issubset(
        {case.key for case in visual.full_visual_cases()}
    )


def test_perceptual_signature_detects_large_visual_change(tmp_path: Path):
    baseline_path = tmp_path / "baseline.png"
    changed_path = tmp_path / "changed.png"
    Image.new("RGB", (320, 180), "white").save(baseline_path)
    Image.new("RGB", (320, 180), "black").save(changed_path)

    baseline = visual.image_signature(baseline_path)
    changed = visual.image_signature(changed_path)
    comparison = visual.compare_signatures(changed, baseline)

    assert comparison["passed"] is False
    assert comparison["thumbnail_mae"] > visual.DEFAULT_THRESHOLDS["thumbnail_mae"]


def test_geometry_gate_enforces_logical_width_and_breakpoint_classes():
    snapshot = {
        "requestedZoom": 150,
        "appliedZoom": 150,
        "requestedDpr": 2,
        "actualDpr": 2,
        "innerWidth": 1280,
        "innerHeight": 720,
        "layoutWidth": 1280 / 1.5,
        "layoutHeight": 720 / 1.5,
        "bodyClasses": [
            "koto-layout-compact",
            "koto-layout-max-1200",
            "koto-layout-max-860",
            "koto-layout-max-900",
        ],
        "shell": {"left": 0, "top": 0, "right": 1280, "bottom": 720},
        "portal": {"left": 0, "top": 0, "right": 1280, "bottom": 720},
        "bodyZoom": 1,
        "shellZoom": 1.5,
        "portalZoom": 1.5,
        "bodyOverflow": "hidden",
        "htmlOverflow": "hidden",
    }
    assert visual.geometry_failures(snapshot) == []


def test_surface_gate_rejects_canvas_below_device_pixel_density():
    metrics = {
        "rect": {
            "left": 0,
            "top": 0,
            "right": 640,
            "bottom": 480,
            "width": 640,
            "height": 480,
        },
        "devicePixelRatio": 2,
        "canvases": [
            {"width": 640, "height": 480, "paintWidth": 640, "paintHeight": 480}
        ],
    }

    assert visual.surface_failures(metrics, (1280, 720)) == [
        "visible canvas backing store is below the device-pixel density"
    ]
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "rect.width >= 120 && rect.height >= 120" in source


def test_release_workflow_runs_visual_smoke_gate():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    package = (ROOT / "web" / "package.json").read_text(encoding="utf-8")

    assert "scripts/ui_visual_regression.py --mode smoke" in workflow
    assert '"visual:smoke"' in package
    assert '"visual:full"' in package
