#!/usr/bin/env python3
"""Koto UI scale visual regression runner.

The full profile sweeps every supported UI zoom over the viewport/DPR matrix
for geometry, then captures a pairwise visual set for the shell and the four
document editors.  Compact perceptual baselines live in source control while
full candidate screenshots and HTML reports stay in ``build/ui-visual``.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import requests
from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "build" / "ui-visual"
DEFAULT_BASELINE = REPO_ROOT / "tests" / "visual_baselines" / "ui_scale" / "chromium.json"

ZOOM_PCTS = tuple(range(70, 151, 5))
DPRS = (1.0, 1.25, 1.5, 2.0)
VIEWPORTS = {
    "desktop": (1440, 900),
    "laptop": (1280, 720),
    "narrow": (900, 700),
}
SURFACES = ("shell", "docx", "xlsx", "pptx", "pdf")
EDITOR_FILES = {
    "docx": "visual-contract.docx",
    "xlsx": "visual-contract.xlsx",
    "pptx": "visual-contract.pptx",
    "pdf": "visual-contract.pdf",
}
SURFACE_SELECTORS = {
    "shell": ".app-shell.koto-unified-workspace",
    "docx": "#wa-docx-editor.active",
    "xlsx": "#wa-xlsx-editor.active",
    "pptx": "#wa-pptx-editor.active",
    "pdf": "#wa-pdf-editor.active",
}

THUMBNAIL_SIZE = (96, 54)
DEFAULT_THRESHOLDS = {
    "thumbnail_mae": 0.18,
    "dhash_distance": 24,
    "minimum_sharpness_ratio": 0.55,
}


@dataclass(frozen=True)
class VisualCase:
    surface: str
    zoom_pct: int
    dpr: float
    viewport_name: str

    @property
    def viewport(self) -> tuple[int, int]:
        return VIEWPORTS[self.viewport_name]

    @property
    def key(self) -> str:
        width, height = self.viewport
        dpr_label = f"{self.dpr:.2f}".replace(".", "p")
        return (
            f"{self.surface}__zoom-{self.zoom_pct:03d}"
            f"__dpr-{dpr_label}__{self.viewport_name}-{width}x{height}"
        )


def _case(surface: str, zoom_pct: int, dpr: float, viewport_name: str) -> VisualCase:
    return VisualCase(surface, zoom_pct, dpr, viewport_name)


def smoke_visual_cases() -> list[VisualCase]:
    shell_anchors = [
        (70, 1.0, "desktop"),
        (100, 1.5, "desktop"),
        (125, 2.0, "narrow"),
        (150, 1.0, "laptop"),
    ]
    editor_anchors = [
        (70, 1.0, "desktop"),
        (100, 1.25, "laptop"),
        (125, 1.5, "narrow"),
        (150, 2.0, "desktop"),
    ]
    cases = [_case("shell", *anchor) for anchor in shell_anchors]
    for index, surface in enumerate(SURFACES[1:]):
        cases.append(_case(surface, *editor_anchors[index]))
        cases.append(_case(surface, *editor_anchors[(index + 2) % len(editor_anchors)]))
    return cases


def full_visual_cases() -> list[VisualCase]:
    # Every zoom appears in a shell screenshot; DPR and viewport rotate so the
    # image set is pairwise rather than a repository-heavy Cartesian product.
    shell_cases = [
        _case(
            "shell",
            zoom_pct,
            DPRS[index % len(DPRS)],
            tuple(VIEWPORTS)[index % len(VIEWPORTS)],
        )
        for index, zoom_pct in enumerate(ZOOM_PCTS)
    ]
    editor_anchors = [
        (70, 1.0, "desktop"),
        (85, 2.0, "laptop"),
        (100, 1.25, "laptop"),
        (110, 1.5, "desktop"),
        (125, 1.5, "narrow"),
        (135, 1.25, "narrow"),
        (145, 1.0, "laptop"),
        (150, 2.0, "desktop"),
    ]
    editor_cases = [
        _case(surface, *anchor)
        for surface in SURFACES[1:]
        for anchor in editor_anchors
    ]
    return shell_cases + editor_cases


def geometry_cases(mode: str) -> list[VisualCase]:
    if mode == "smoke":
        return [case for case in smoke_visual_cases() if case.surface == "shell"]
    return [
        _case("shell", zoom_pct, dpr, viewport_name)
        for dpr in DPRS
        for viewport_name in VIEWPORTS
        for zoom_pct in ZOOM_PCTS
    ]


def validate_matrix_contract(cases: Iterable[VisualCase], *, full: bool) -> None:
    cases = list(cases)
    assert {case.surface for case in cases} == set(SURFACES)
    assert {case.dpr for case in cases} == set(DPRS)
    assert {case.viewport_name for case in cases} == set(VIEWPORTS)
    zooms = {case.zoom_pct for case in cases}
    assert min(zooms) == 70 and max(zooms) == 150
    if full:
        assert set(ZOOM_PCTS).issubset(zooms)


def _dhash(image: Image.Image) -> str:
    gray = ImageOps.grayscale(image).resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.get_flattened_data())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | int(pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return f"{bits:016x}"


def _sharpness(image: Image.Image) -> float:
    edges = ImageOps.grayscale(image).filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(edges).var[0])


def _thumbnail(image: Image.Image) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), THUMBNAIL_SIZE, method=Image.Resampling.LANCZOS)


def image_signature(image_path: Path) -> dict[str, object]:
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        thumb = _thumbnail(image)
        buffer = io.BytesIO()
        thumb.save(buffer, format="PNG", optimize=True)
        stat = ImageStat.Stat(thumb)
        return {
            "width": image.width,
            "height": image.height,
            "dhash": _dhash(thumb),
            "sharpness": round(_sharpness(thumb), 4),
            "mean_rgb": [round(value, 3) for value in stat.mean],
            "thumbnail_png": base64.b64encode(buffer.getvalue()).decode("ascii"),
        }


def _decode_thumbnail(signature: dict[str, object]) -> Image.Image:
    raw = base64.b64decode(str(signature["thumbnail_png"]))
    with Image.open(io.BytesIO(raw)) as image:
        return image.convert("RGB")


def _hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def compare_signatures(current: dict[str, object], baseline: dict[str, object]) -> dict[str, object]:
    current_thumb = _decode_thumbnail(current)
    baseline_thumb = _decode_thumbnail(baseline)
    diff = ImageChops.difference(current_thumb, baseline_thumb)
    mae = sum(ImageStat.Stat(diff).mean) / (3 * 255)
    baseline_sharpness = max(float(baseline.get("sharpness", 0)), 0.0001)
    sharpness_ratio = float(current.get("sharpness", 0)) / baseline_sharpness
    dhash_distance = _hamming(str(current["dhash"]), str(baseline["dhash"]))
    passed = (
        abs(int(current["width"]) - int(baseline["width"])) <= 2
        and abs(int(current["height"]) - int(baseline["height"])) <= 2
        and mae <= DEFAULT_THRESHOLDS["thumbnail_mae"]
        and dhash_distance <= DEFAULT_THRESHOLDS["dhash_distance"]
        and sharpness_ratio >= DEFAULT_THRESHOLDS["minimum_sharpness_ratio"]
    )
    return {
        "passed": passed,
        "thumbnail_mae": round(mae, 5),
        "dhash_distance": dhash_distance,
        "sharpness_ratio": round(sharpness_ratio, 4),
    }


def write_thumbnail_diff(current: dict[str, object], baseline: dict[str, object], path: Path) -> None:
    diff = ImageChops.difference(_decode_thumbnail(current), _decode_thumbnail(baseline))
    diff = ImageOps.autocontrast(ImageOps.grayscale(diff)).convert("RGB")
    diff = diff.resize((768, 432), Image.Resampling.NEAREST)
    path.parent.mkdir(parents=True, exist_ok=True)
    diff.save(path, optimize=True)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def create_visual_fixtures(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)

    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    document = Document()
    title = document.add_heading("Koto Visual Contract", level=1)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_paragraph("UI scale · logical viewport · deterministic typography")
    table = document.add_table(rows=4, cols=3)
    table.style = "Table Grid"
    for col, value in enumerate(("Metric", "Current", "Target")):
        table.cell(0, col).text = value
    for row, values in enumerate((("Clarity", "98", "100"), ("Alignment", "96", "100"), ("Overflow", "0", "0")), 1):
        for col, value in enumerate(values):
            table.cell(row, col).text = value
    document.add_heading("Stable rendering", level=2)
    document.add_paragraph("The quick brown fox jumps over the lazy dog. 0123456789")
    document.save(workspace / EDITOR_FILES["docx"])

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Scale Matrix"
    rows = [
        ("Product", "2026 Q1", "2026 Q2", "Growth"),
        ("Alpha", 120000, 156000, "=C2/B2-1"),
        ("Beta", 98000, 132000, "=C3/B3-1"),
        ("Gamma", 76000, 91000, "=C4/B4-1"),
        ("Total", "=SUM(B2:B4)", "=SUM(C2:C4)", "=C5/B5-1"),
    ]
    for row in rows:
        sheet.append(row)
    header_fill = PatternFill("solid", fgColor="1D4ED8")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center")
    for cell in sheet[5]:
        cell.font = Font(bold=True)
    for column in ("B", "C"):
        for cell in sheet[column][1:]:
            cell.number_format = "#,##0"
    for cell in sheet["D"][1:]:
        cell.number_format = "0.0%"
    sheet.freeze_panes = "B2"
    sheet.column_dimensions["A"].width = 20
    for column in ("B", "C", "D"):
        sheet.column_dimensions[column].width = 16
    workbook.save(workspace / EDITOR_FILES["xlsx"])

    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    background = slide.background.fill
    background.solid()
    background.fore_color.rgb = RGBColor(245, 247, 252)
    heading = slide.shapes.add_textbox(Inches(0.8), Inches(0.7), Inches(11.8), Inches(1.0))
    paragraph = heading.text_frame.paragraphs[0]
    paragraph.text = "Koto UI Scale Contract"
    paragraph.font.size = Pt(32)
    paragraph.font.bold = True
    paragraph.font.color.rgb = RGBColor(15, 23, 42)
    for index, (label, color) in enumerate((("Logical viewport", "2563EB"), ("Crisp canvas", "059669"), ("Stable pointer", "7C3AED"))):
        box = slide.shapes.add_textbox(Inches(0.9 + index * 4.1), Inches(2.4), Inches(3.5), Inches(2.1))
        box.fill.solid()
        box.fill.fore_color.rgb = RGBColor.from_string(color)
        box.line.fill.background()
        text = box.text_frame.paragraphs[0]
        text.text = label
        text.font.size = Pt(20)
        text.font.bold = True
        text.font.color.rgb = RGBColor(255, 255, 255)
    presentation.save(workspace / EDITOR_FILES["pptx"])

    pdf_path = workspace / EDITOR_FILES["pdf"]
    pdf = canvas.Canvas(str(pdf_path), pagesize=A4)
    width, height = A4
    pdf.setFillColor(HexColor("#0F172A"))
    pdf.setFont("Helvetica-Bold", 26)
    pdf.drawString(56, height - 76, "Koto Visual Contract")
    pdf.setFont("Helvetica", 12)
    pdf.setFillColor(HexColor("#334155"))
    pdf.drawString(56, height - 108, "PDF canvas, text layer and annotation geometry")
    pdf.setFillColor(HexColor("#DBEAFE"))
    pdf.roundRect(56, height - 260, width - 112, 110, 12, fill=1, stroke=0)
    pdf.setFillColor(HexColor("#1E3A8A"))
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(78, height - 195, "Readable at every supported scale")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(78, height - 222, "70%  100%  125%  150%  |  DPR 1.0  1.25  1.5  2.0")
    pdf.showPage()
    pdf.save()


def write_visual_settings(path: Path, workspace: Path) -> None:
    settings = {
        "storage": {
            "workspace_dir": str(workspace),
            "documents_dir": str(workspace / "documents"),
            "images_dir": str(workspace / "images"),
            "chats_dir": str(workspace / "chats"),
        },
        "appearance": {"theme": "light", "language": "zh-CN", "ui_zoom": 1.0},
        "ai": {
            "default_model": "auto",
            "use_local_only": False,
            "show_thinking": False,
            "show_task_type": False,
            "auto_save_files": False,
        },
        "proxy": {"enabled": False, "auto_detect": False, "manual_proxy": ""},
    }
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def start_server(runtime_dir: Path, workspace: Path, output_dir: Path) -> tuple[subprocess.Popen, str, object]:
    port = _free_port()
    settings_path = runtime_dir / "user_settings.json"
    write_visual_settings(settings_path, workspace)
    env = os.environ.copy()
    env.update(
        {
            "KOTO_PORT": str(port),
            "KOTO_DEPLOY_MODE": "local",
            "KOTO_AUTH_ENABLED": "false",
            "FLASK_DEBUG": "false",
            "KOTO_WORKSPACE_DIR": str(workspace),
            "KOTO_USER_SETTINGS_PATH": str(settings_path),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": os.pathsep.join([str(REPO_ROOT), str(REPO_ROOT / "src")]),
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(output_dir / "server.log", "w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "src" / "server.py")],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=log_file,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 75
    while time.time() < deadline:
        if process.poll() is not None:
            break
        try:
            if requests.get(f"{base_url}/api/ping", timeout=3).status_code == 200:
                return process, base_url, log_file
        except requests.RequestException:
            pass
        time.sleep(0.5)
    process.terminate()
    log_file.close()
    tail = (output_dir / "server.log").read_text(encoding="utf-8", errors="replace")[-3000:]
    raise RuntimeError(f"Visual regression server failed to start.\n{tail}")


def _install_determinism(page) -> None:
    page.route(
        "**/api/setup/status",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"initialized":true,"has_api_key":true}'),
    )
    # The frontend observer long-polls for remote actions. It is unrelated to
    # rendering and can otherwise leave dozens of 25-second requests alive
    # while the matrix rotates browser contexts.
    page.route(
        "**/api/mcp/frontend-action?*",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"action":null}'),
    )
    page.route(
        "**/api/mcp/frontend-event",
        lambda route: route.fulfill(status=204, body=""),
    )
    page.add_init_script(
        """
        localStorage.setItem('koto.theme', 'light');
        localStorage.setItem('koto.uiZoom', '1');
        localStorage.removeItem('wa_split_sizes_v2');
        localStorage.removeItem('wa_split_sizes_embedded_v3');
        """
    )


DETERMINISTIC_CSS = """
*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }
.loading-overlay, #startupSplash, .wa-toast, #wa-toast, .notification-container { display: none !important; }
.wa-footer-model-name, .status-dot, .time-info, [data-runtime-status] { visibility: hidden !important; }
"""


def _prepare_page(page, base_url: str) -> None:
    _install_determinism(page)
    last_error = None
    for attempt in range(2):
        try:
            page.goto(base_url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_function(
                "() => typeof window.setUIZoom === 'function' && typeof document.__kotoFeatureRegistry__?.openWorkspaceFile === 'function'",
                timeout=45_000,
            )
            last_error = None
            break
        except Exception as error:
            last_error = error
            if attempt == 0:
                page.wait_for_timeout(250)
    if last_error is not None:
        raise last_error
    page.wait_for_function(
        "() => typeof window._waSplit?.setSizes === 'function'",
        timeout=15_000,
    )
    page.add_style_tag(content=DETERMINISTIC_CSS)
    page.evaluate("() => document.fonts?.ready")
    page.wait_for_timeout(350)


def _set_zoom(page, zoom_pct: int) -> None:
    page.evaluate(
        "pct => window.setUIZoom(String(pct / 100), true, false)",
        zoom_pct,
    )
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    # Split.js can finish its first min-size pass at slightly different times
    # after heavy editor bundles load. Reapply the canonical layout so visual
    # dimensions are deterministic rather than timing-dependent.
    page.evaluate(
        """() => {
          window._waSplit?.setSizes?.([15, 53, 32]);
          document.__kotoFeatureRegistry__?.refreshWorkspaceLayout?.();
          return new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }"""
    )


def _geometry_snapshot(page, case: VisualCase) -> dict[str, object]:
    return page.evaluate(
        """({ zoomPct, dpr }) => {
          const shell = document.querySelector('.app-shell.koto-unified-workspace');
          const portal = document.getElementById('koto-ui-portal-root');
          const rect = shell?.getBoundingClientRect();
          const portalRect = portal?.getBoundingClientRect();
          const rootStyle = getComputedStyle(document.documentElement);
          const layoutWidth = Number(rootStyle.getPropertyValue('--koto-layout-width').replace('px', ''));
          const layoutHeight = Number(rootStyle.getPropertyValue('--koto-layout-height').replace('px', ''));
          return {
            requestedZoom: zoomPct,
            appliedZoom: Number(document.documentElement.dataset.kotoUiZoom || 1) * 100,
            requestedDpr: dpr,
            actualDpr: window.devicePixelRatio,
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            layoutWidth,
            layoutHeight,
            bodyClasses: [...document.body.classList].filter(name => name.startsWith('koto-layout-')).sort(),
            shell: rect ? {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height} : null,
            portal: portalRect ? {left: portalRect.left, top: portalRect.top, right: portalRect.right, bottom: portalRect.bottom, width: portalRect.width, height: portalRect.height} : null,
            bodyZoom: Number(getComputedStyle(document.body).zoom || 1),
            shellZoom: Number(shell ? getComputedStyle(shell).zoom : 0),
            portalZoom: Number(portal ? getComputedStyle(portal).zoom : 0),
            bodyOverflow: getComputedStyle(document.body).overflow,
            htmlOverflow: getComputedStyle(document.documentElement).overflow,
          };
        }""",
        {"zoomPct": case.zoom_pct, "dpr": case.dpr},
    )


def _expected_breakpoint_classes(logical_width: float) -> list[str]:
    classes = [
        f"koto-layout-max-{breakpoint}"
        for breakpoint in (1200, 900, 860, 768, 640, 520, 480)
        if logical_width <= breakpoint
    ]
    if logical_width < 1100:
        classes.append("koto-layout-compact")
    if logical_width < 760:
        classes.append("koto-layout-phone")
    return sorted(classes)


def geometry_failures(snapshot: dict[str, object]) -> list[str]:
    failures: list[str] = []
    tolerance = 1.5
    shell = snapshot.get("shell") or {}
    for key, expected in (
        ("left", 0),
        ("top", 0),
        ("right", snapshot["innerWidth"]),
        ("bottom", snapshot["innerHeight"]),
    ):
        if abs(float(shell.get(key, math.inf)) - float(expected)) > tolerance:
            failures.append(f"shell.{key}={shell.get(key)!r}, expected {expected!r}")
    portal = snapshot.get("portal") or {}
    for key, expected in (
        ("left", 0),
        ("top", 0),
        ("right", snapshot["innerWidth"]),
        ("bottom", snapshot["innerHeight"]),
    ):
        if abs(float(portal.get(key, math.inf)) - float(expected)) > tolerance:
            failures.append(f"portal.{key}={portal.get(key)!r}, expected {expected!r}")
    if abs(float(snapshot["appliedZoom"]) - float(snapshot["requestedZoom"])) > 0.1:
        failures.append("requested UI zoom was not applied")
    if abs(float(snapshot["actualDpr"]) - float(snapshot["requestedDpr"])) > 0.01:
        failures.append("requested device scale factor was not applied")
    requested_zoom = float(snapshot["requestedZoom"]) / 100
    if abs(float(snapshot.get("bodyZoom", 1)) - 1) > 0.01:
        failures.append("body must remain outside the application zoom boundary")
    if abs(float(snapshot.get("shellZoom", 0)) - requested_zoom) > 0.01:
        failures.append("application shell zoom boundary was not applied")
    if abs(float(snapshot.get("portalZoom", 0)) - requested_zoom) > 0.01:
        failures.append("UI portal zoom boundary was not applied")
    expected_width = float(snapshot["innerWidth"]) / (float(snapshot["requestedZoom"]) / 100)
    if abs(float(snapshot["layoutWidth"]) - expected_width) > 0.1:
        failures.append("logical viewport width is not compensated")
    expected_classes = _expected_breakpoint_classes(float(snapshot["layoutWidth"]))
    if snapshot["bodyClasses"] != expected_classes:
        failures.append(f"breakpoint classes {snapshot['bodyClasses']!r}, expected {expected_classes!r}")
    if snapshot["bodyOverflow"] != "hidden" or snapshot["htmlOverflow"] != "hidden":
        failures.append("root overflow must remain hidden")
    return failures


def _open_surface(page, surface: str) -> None:
    if surface == "shell":
        return
    filename = EDITOR_FILES[surface]
    page.evaluate(
        "path => document.__kotoFeatureRegistry__.openWorkspaceFile(path)",
        filename,
    )
    selector = SURFACE_SELECTORS[surface]
    page.locator(selector).wait_for(state="visible", timeout=60_000)
    if surface == "docx":
        page.locator("#wa-docx-editor .ProseMirror").wait_for(state="visible", timeout=45_000)
    elif surface == "xlsx":
        page.locator("#wa-xlsx-viewport canvas").first.wait_for(state="visible", timeout=60_000)
    elif surface == "pptx":
        page.locator("#wa-pptx-slide-canvas").wait_for(state="visible", timeout=45_000)
    elif surface == "pdf":
        page.locator("#wa-pdf-viewer .wa-pdf-page-wrap canvas").first.wait_for(state="visible", timeout=60_000)
    page.wait_for_timeout(650)


def _surface_metrics(page, case: VisualCase) -> dict[str, object]:
    selector = SURFACE_SELECTORS[case.surface]
    return page.evaluate(
        """selector => {
          const el = document.querySelector(selector);
          const rect = el?.getBoundingClientRect();
          const canvases = el ? [...el.querySelectorAll('canvas')]
            .map(canvas => {
              const r = canvas.getBoundingClientRect();
              return {width: canvas.width, height: canvas.height, paintWidth: r.width, paintHeight: r.height};
            })
            .filter(item => item.paintWidth >= 80 && item.paintHeight >= 40)
            .slice(0, 8) : [];
          return {
            rect: rect ? {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height} : null,
            devicePixelRatio: window.devicePixelRatio || 1,
            canvases,
          };
        }""",
        selector,
    )


def surface_failures(metrics: dict[str, object], viewport: tuple[int, int]) -> list[str]:
    failures: list[str] = []
    rect = metrics.get("rect") or {}
    if float(rect.get("width", 0)) < 120 or float(rect.get("height", 0)) < 120:
        failures.append("editor surface is missing or too small")
    width, height = viewport
    if float(rect.get("left", 0)) < -2 or float(rect.get("right", width)) > width + 2:
        failures.append("editor surface overflows horizontally")
    if float(rect.get("top", 0)) < -2 or float(rect.get("bottom", height)) > height + 2:
        failures.append("editor surface overflows vertically")
    for canvas in metrics.get("canvases", []):
        if canvas["width"] <= 0 or canvas["height"] <= 0:
            failures.append("visible canvas has an empty backing store")
            continue
        expected_density = float(metrics.get("devicePixelRatio", 1))
        density_x = float(canvas["width"]) / max(float(canvas["paintWidth"]), 0.001)
        density_y = float(canvas["height"]) / max(float(canvas["paintHeight"]), 0.001)
        if density_x < expected_density * 0.9 or density_y < expected_density * 0.9:
            failures.append(
                "visible canvas backing store is below the device-pixel density"
            )
    return failures


def _group_cases(cases: Iterable[VisualCase]) -> dict[tuple[float, str], list[VisualCase]]:
    grouped: dict[tuple[float, str], list[VisualCase]] = {}
    for case in cases:
        grouped.setdefault((case.dpr, case.viewport_name), []).append(case)
    return grouped


def load_baseline(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": 1, "engine": "chromium", "cases": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_report(output_dir: Path, summary: dict[str, object]) -> None:
    report_json = output_dir / "report.json"
    report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for result in summary["visualResults"]:
        status = "PASS" if result["passed"] else "FAIL"
        candidate = html.escape(result["candidate"])
        comparison = html.escape(json.dumps(result.get("comparison") or {}, ensure_ascii=False))
        baseline_thumb = result.get("baselineThumbnail") or ""
        baseline_cell = f'<img src="data:image/png;base64,{baseline_thumb}">' if baseline_thumb else "—"
        diff_cell = f'<img src="{html.escape(result["diff"])}">' if result.get("diff") else "—"
        rows.append(
            f"<tr class='{status.lower()}'><td>{status}</td><td>{html.escape(result['key'])}</td>"
            f"<td><img src='{candidate}'></td><td>{baseline_cell}</td><td>{diff_cell}</td>"
            f"<td><code>{comparison}</code></td></tr>"
        )
    failures = "".join(f"<li>{html.escape(item)}</li>" for item in summary["failures"])
    page = f"""<!doctype html><meta charset='utf-8'><title>Koto UI visual regression</title>
<style>body{{font:14px/1.45 system-ui;margin:24px;color:#172033}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd4e0;padding:8px;vertical-align:top}}img{{width:240px;max-height:150px;object-fit:contain;background:#eef2f7}}.fail{{background:#fff0f0}}.pass{{background:#f2fff6}}code{{white-space:pre-wrap;font-size:11px}}</style>
<h1>Koto UI visual regression</h1><p>Mode: {summary['mode']} · geometry: {summary['geometryCount']} · visual: {summary['visualCount']} · failures: {len(summary['failures'])}</p>
<ul>{failures}</ul><table><thead><tr><th>Status</th><th>Case</th><th>Candidate</th><th>Baseline</th><th>Diff</th><th>Metrics</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"""
    (output_dir / "report.html").write_text(page, encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit("Install Playwright: pip install playwright && python -m playwright install chromium") from exc

    visual_cases = smoke_visual_cases() if args.mode == "smoke" else full_visual_cases()
    validate_matrix_contract(visual_cases, full=args.mode == "full")
    geometry = geometry_cases(args.mode)
    default_output = DEFAULT_OUTPUT if args.mode == "full" else DEFAULT_OUTPUT.parent / "ui-visual-smoke"
    output_dir = Path(args.output or default_output).resolve()
    candidates_dir = output_dir / "candidates"
    diffs_dir = output_dir / "diffs"
    for generated_dir in (candidates_dir, diffs_dir):
        if generated_dir.exists():
            shutil.rmtree(generated_dir)
    candidates_dir.mkdir(parents=True, exist_ok=True)
    diffs_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = Path(args.baseline).resolve()
    baseline = load_baseline(baseline_path)
    if args.update_baselines and args.mode == "full":
        baseline["cases"] = {}
    baseline_cases: dict[str, object] = baseline.setdefault("cases", {})
    failures: list[str] = []
    geometry_results: list[dict[str, object]] = []
    visual_results: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="koto-ui-visual-") as temp:
        runtime_dir = Path(temp)
        workspace = runtime_dir / "workspace"
        create_visual_fixtures(workspace)
        server, base_url, server_log = start_server(runtime_dir, workspace, output_dir)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=not args.show)
                try:
                    for (dpr, viewport_name), cases in _group_cases(geometry).items():
                        width, height = VIEWPORTS[viewport_name]
                        context = browser.new_context(
                            viewport={"width": width, "height": height},
                            device_scale_factor=dpr,
                            color_scheme="light",
                            reduced_motion="reduce",
                            locale="zh-CN",
                        )
                        page = context.new_page()
                        _prepare_page(page, base_url)
                        for case in cases:
                            _set_zoom(page, case.zoom_pct)
                            snapshot = _geometry_snapshot(page, case)
                            case_failures = geometry_failures(snapshot)
                            geometry_results.append({"key": case.key, "metrics": snapshot, "failures": case_failures})
                            failures.extend(f"{case.key}: {failure}" for failure in case_failures)
                        context.close()

                    for (dpr, viewport_name), cases in _group_cases(visual_cases).items():
                        width, height = VIEWPORTS[viewport_name]
                        context = browser.new_context(
                            viewport={"width": width, "height": height},
                            device_scale_factor=dpr,
                            color_scheme="light",
                            reduced_motion="reduce",
                            locale="zh-CN",
                        )
                        page = context.new_page()
                        _prepare_page(page, base_url)
                        current_surface = "shell"
                        for case in cases:
                            if case.surface != current_surface:
                                _open_surface(page, case.surface)
                                current_surface = case.surface
                            _set_zoom(page, case.zoom_pct)
                            if case.surface != "shell":
                                page.wait_for_function(
                                    """selector => {
                                      const rect = document.querySelector(selector)?.getBoundingClientRect();
                                      return Boolean(rect && rect.width >= 120 && rect.height >= 120);
                                    }""",
                                    arg=SURFACE_SELECTORS[case.surface],
                                    timeout=10_000,
                                )
                            page.wait_for_timeout(120)
                            metrics = _surface_metrics(page, case)
                            case_failures = surface_failures(metrics, case.viewport)
                            failures.extend(f"{case.key}: {failure}" for failure in case_failures)
                            candidate_path = candidates_dir / f"{case.key}.png"
                            page.locator(SURFACE_SELECTORS[case.surface]).screenshot(
                                path=str(candidate_path),
                                animations="disabled",
                                caret="hide",
                            )
                            signature = image_signature(candidate_path)
                            baseline_signature = baseline_cases.get(case.key)
                            comparison = None
                            diff_path = None
                            passed = not case_failures
                            if args.update_baselines:
                                baseline_cases[case.key] = signature
                            elif baseline_signature:
                                comparison = compare_signatures(signature, baseline_signature)
                                passed = passed and bool(comparison["passed"])
                                if not comparison["passed"]:
                                    diff_path = diffs_dir / f"{case.key}.png"
                                    write_thumbnail_diff(signature, baseline_signature, diff_path)
                                    failures.append(f"{case.key}: visual signature exceeded baseline thresholds")
                            else:
                                passed = False
                                failures.append(f"{case.key}: visual baseline is missing")
                            visual_results.append(
                                {
                                    "key": case.key,
                                    "case": asdict(case),
                                    "passed": passed,
                                    "candidate": candidate_path.relative_to(output_dir).as_posix(),
                                    "diff": diff_path.relative_to(output_dir).as_posix() if diff_path else None,
                                    "metrics": metrics,
                                    "signature": {k: v for k, v in signature.items() if k != "thumbnail_png"},
                                    "baselineThumbnail": baseline_signature.get("thumbnail_png") if baseline_signature else None,
                                    "comparison": comparison,
                                }
                            )
                        context.close()
                finally:
                    browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server.kill()
            server_log.close()

    if args.update_baselines:
        baseline.update(
            {
                "version": 1,
                "engine": "chromium",
                "matrix": {
                    "zooms": list(ZOOM_PCTS),
                    "dprs": list(DPRS),
                    "viewports": VIEWPORTS,
                    "surfaces": list(SURFACES),
                },
                "thresholds": DEFAULT_THRESHOLDS,
            }
        )
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "version": 1,
        "mode": args.mode,
        "geometryCount": len(geometry_results),
        "visualCount": len(visual_results),
        "failures": failures,
        "geometryResults": geometry_results,
        "visualResults": visual_results,
    }
    write_report(output_dir, summary)
    print(
        f"UI visual regression: {len(geometry_results)} geometry, "
        f"{len(visual_results)} screenshots, {len(failures)} failures"
    )
    print(f"Report: {output_dir / 'report.html'}")
    if args.update_baselines:
        print(f"Baseline updated: {baseline_path}")
    return 1 if failures else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--update-baselines", action="store_true")
    parser.add_argument("--show", action="store_true", help="Run Chromium headed for local debugging")
    parser.add_argument("--output", default=None)
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
