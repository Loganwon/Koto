#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnostic + regression test for slide 8 text overlap issue.

Slide 8 of 植谱生物 投资报告.pptx has a layout where:
  - Shape 139: wide text box (body text, transparent background)
  - Shape 141: right-side credentials box (transparent, on top)
Both overlap physically; shape 139's text must NOT visually flow into shape 141's area.

This test:
1. Reads raw PPTX XML to confirm shape 139's actual bodyPr insets (lIns/rIns/tIns/bIns)
2. Verifies parse_pptx_geometry extracts textInsets correctly
3. Asserts that shape 139's effective text width (after insets) does NOT extend into shape 141
4. Asserts that the rendering padding math is correct
"""

import os
import sys
import zipfile

import lxml.etree as ET
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PPTX_PATH = os.path.join(os.path.dirname(__file__), "..", "workspace", "植谱生物 投资报告.pptx")
SLIDE_IDX = 7   # slide 8 (0-based)
SHAPE_139_ID = 139
SHAPE_141_ID = 141

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"


# ── helpers ──────────────────────────────────────────────────────────────────

def _load_pptx_slide_xml(pptx_path: str, slide_idx: int) -> ET.Element:
    """Return the root XML element of the given slide from the raw PPTX zip."""
    with zipfile.ZipFile(pptx_path, "r") as z:
        names = z.namelist()
        slide_files = sorted(
            [n for n in names if n.startswith("ppt/slides/slide") and "/rels/" not in n],
            key=lambda x: int("".join(c for c in x.split("/")[-1] if c.isdigit()) or "0"),
        )
        target = slide_files[slide_idx]
        raw = z.read(target)
    return ET.fromstring(raw)


def _find_sp_by_id(root: ET.Element, shape_id: int) -> ET.Element | None:
    """Find a <p:sp> element whose <p:nvSpPr><p:cNvPr id="..."> matches shape_id."""
    for sp in root.iter(f"{{{NS_P}}}sp"):
        nv = sp.find(f".//{{{NS_P}}}cNvPr")
        if nv is not None and nv.get("id") == str(shape_id):
            return sp
    return None


def _get_bodypr(sp: ET.Element) -> ET.Element | None:
    return sp.find(f".//{{{NS_A}}}bodyPr")


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pptx_path():
    if not os.path.exists(PPTX_PATH):
        pytest.skip(f"Test PPTX not found: {PPTX_PATH}")
    return PPTX_PATH


@pytest.fixture(scope="module")
def parsed_data(pptx_path):
    from app.core.file.file_parser import parse_pptx_geometry
    d = parse_pptx_geometry(pptx_path)
    # Normalise key name: parser uses snake_case, expose both
    d.setdefault("slideWidthEmu", d.get("slide_width_emu", 9144000))
    d.setdefault("slideHeightEmu", d.get("slide_height_emu", 6858000))
    return d


@pytest.fixture(scope="module")
def slide8(parsed_data):
    return parsed_data["slides"][SLIDE_IDX]


@pytest.fixture(scope="module")
def shapes_by_id(slide8):
    return {s["id"]: s for s in slide8["shapes"]}


@pytest.fixture(scope="module")
def raw_slide_root(pptx_path):
    return _load_pptx_slide_xml(pptx_path, SLIDE_IDX)


# ── diagnostic print (always runs, not a test) ────────────────────────────────

def _print_slide8_shapes(slide8, slide_width_emu, scale=640):
    s = scale / slide_width_emu
    print(f"\n{'='*70}")
    print(f"Slide 8 shapes  (scale={scale}px / {slide_width_emu} EMU = {s:.7f})")
    print(f"{'id':>4} {'z':>4} {'type':<7} {'left':>7} {'top':>6} {'w':>7} {'h':>6}  {'pxL':>4} {'pxT':>4} {'pxW':>4} {'pxH':>4}  {'anch':5}  insets(l,t,r,b px)")
    for sh in sorted(slide8["shapes"], key=lambda x: x.get("z_order", 0)):
        l = sh["left"]; t = sh["top"]; w = sh["width"]; h = sh["height"]
        ins = sh.get("textInsets", {})
        il = round(ins.get("l", 91440) * s)
        it_ = round(ins.get("t", 45720) * s)
        ir = round(ins.get("r", 91440) * s)
        ib = round(ins.get("b", 45720) * s)
        print(
            f"{sh['id']:>4} {sh.get('z_order','?'):>4} {sh.get('_type','?'):<7}"
            f" {l:>7} {t:>6} {w:>7} {h:>6}"
            f"  {round(l*s):>4} {round(t*s):>4} {round(w*s):>4} {round(h*s):>4}"
            f"  {sh.get('textAnchor','-'):<5}  ({il},{it_},{ir},{ib})"
        )
    print(f"{'='*70}\n")


# ── Test 1: raw XML has expected bodyPr attributes for shape 139 ──────────────

def test_shape139_bodypr_raw_xml(raw_slide_root, parsed_data):
    """Read shape 139's bodyPr directly from PPTX XML and print actual lIns/rIns."""
    sp = _find_sp_by_id(raw_slide_root, SHAPE_139_ID)
    assert sp is not None, f"Shape {SHAPE_139_ID} not found in raw slide XML"

    bodypr = _get_bodypr(sp)
    assert bodypr is not None, f"Shape {SHAPE_139_ID} has no <a:bodyPr>"

    lIns = bodypr.get("lIns")
    tIns = bodypr.get("tIns")
    rIns = bodypr.get("rIns")
    bIns = bodypr.get("bIns")

    sW = parsed_data.get("slideWidthEmu", 9144000)
    scale = 640 / sW

    print("\nShape 139 bodyPr raw XML:")
    print(ET.tostring(bodypr, pretty_print=True).decode())
    print("  lIns=%s  tIns=%s  rIns=%s  bIns=%s" % (lIns, tIns, rIns, bIns))
    if rIns is not None:
        print("  rIns as px (scale=640): %d" % round(int(rIns) * scale))
    else:
        print("  rIns is ABSENT -> default 91440 EMU = %dpx" % round(91440 * scale))


# ── Test 2: shape 141 bodyPr too ──────────────────────────────────────────────

def test_shape141_bodypr_raw_xml(raw_slide_root, parsed_data):
    """Read shape 141's bodyPr and position."""
    sp = _find_sp_by_id(raw_slide_root, SHAPE_141_ID)
    assert sp is not None, f"Shape {SHAPE_141_ID} not found in raw slide XML"

    bodypr = _get_bodypr(sp)
    if bodypr is not None:
        print(f"\nShape 141 bodyPr raw XML:")
        print(ET.tostring(bodypr, pretty_print=True).decode())

    # Also look at spPr / xfrm for position
    spPr = sp.find(f".//{{{NS_P}}}spPr")
    if spPr is None:
        spPr = sp.find(f".//{{{NS_A}}}xfrm")
    if spPr is not None:
        print(f"\nShape 141 spPr XML (first 400 chars):")
        print(ET.tostring(spPr, pretty_print=True).decode()[:400])


# ── Test 3: parsed textInsets match raw XML ────────────────────────────────────

def test_textinsets_match_raw_xml(raw_slide_root, shapes_by_id, parsed_data):
    """Verify parse_pptx_geometry extracts textInsets from bodyPr.

    NOTE: l/t/b insets must match the raw XML values exactly.
    The r inset may be LARGER than the XML value because the text-exclusion-zone
    post-processing step expands it to prevent text flowing under overlapping
    higher-z-order shapes (shape 141 in this case).
    """
    sp = _find_sp_by_id(raw_slide_root, SHAPE_139_ID)
    assert sp is not None

    bodypr = _get_bodypr(sp)
    assert bodypr is not None

    raw_l = int(bodypr.get("lIns") or 91440)
    raw_t = int(bodypr.get("tIns") or 45720)
    raw_r = int(bodypr.get("rIns") or 91440)
    raw_b = int(bodypr.get("bIns") or 45720)

    shape_data = shapes_by_id.get(SHAPE_139_ID)
    assert shape_data is not None, "Shape %d not found in parsed data" % SHAPE_139_ID

    parsed_ins = shape_data.get("textInsets", {})
    # l/t/b must match the PPTX XML exactly
    assert parsed_ins.get("l") == raw_l, "lIns mismatch: parsed=%s raw=%s" % (parsed_ins.get("l"), raw_l)
    assert parsed_ins.get("t") == raw_t, "tIns mismatch: parsed=%s raw=%s" % (parsed_ins.get("t"), raw_t)
    assert parsed_ins.get("b") == raw_b, "bIns mismatch: parsed=%s raw=%s" % (parsed_ins.get("b"), raw_b)
    # r must be >= raw value (exclusion zone may expand it)
    assert parsed_ins.get("r", 0) >= raw_r, "rIns should be >= raw XML value; got %s" % parsed_ins.get("r")

    print("\nShape 139 textInsets: raw_r=%d  parsed_r=%d (exclusion zone expanded by %d EMU)" % (
        raw_r, parsed_ins.get("r", raw_r), parsed_ins.get("r", raw_r) - raw_r))


# ── Test 4: shape 139's text area doesn't reach shape 141 ─────────────────────

def test_shape139_text_area_clears_shape141(shapes_by_id, slide8, parsed_data):
    """
    Shape 139's effective text area (after right inset) must not extend into
    shape 141's horizontal range. This ensures at a renderer level that applying
    the PPTX-specified padding will prevent text overlap.
    """
    sW = parsed_data.get("slideWidthEmu", 9144000)
    _print_slide8_shapes(slide8, sW)

    s139 = shapes_by_id.get(SHAPE_139_ID)
    s141 = shapes_by_id.get(SHAPE_141_ID)
    assert s139 is not None and s141 is not None

    ins139 = s139.get("textInsets", {"l": 91440, "t": 45720, "r": 91440, "b": 45720})

    # Effective right edge of shape 139's text content area
    text_right_emu = s139["left"] + s139["width"] - ins139.get("r", 91440)
    # Left edge of shape 141
    shape141_left_emu = s141["left"]

    scale = 640 / sW
    print(f"\n  Shape 139: left={s139['left']} w={s139['width']} rIns={ins139.get('r', 91440)}")
    print(f"  Shape 139 text right edge: {text_right_emu} EMU = {round(text_right_emu * scale)}px")
    print(f"  Shape 141 left edge:       {shape141_left_emu} EMU = {round(shape141_left_emu * scale)}px")

    if text_right_emu <= shape141_left_emu:
        print(f"  ✅ Text area clears shape 141 (gap={round((shape141_left_emu - text_right_emu) * scale)}px)")
    else:
        overlap_px = round((text_right_emu - shape141_left_emu) * scale)
        print(f"  ❌ Text area OVERLAPS shape 141 by {overlap_px}px")
        print(f"     → rIns needs to be at least {s139['left'] + s139['width'] - shape141_left_emu} EMU")
        print(f"     → Currently rIns = {ins139.get('r', 91440)} EMU")

    # This assertion documents the REQUIRED behaviour for no-overlap rendering.
    # If it fails, the rIns is too small and we need a different strategy
    # (e.g. set explicit rIns in the parser based on overlapping shapes).
    assert text_right_emu <= shape141_left_emu, (
        f"Shape 139 text area ({text_right_emu} EMU) extends into shape 141 ({shape141_left_emu} EMU). "
        f"rIns={ins139.get('r', 91440)} is too small — need >={s139['left'] + s139['width'] - shape141_left_emu}"
    )


# ── Test 5: no-overlap check for all overlapping shape pairs ──────────────────

def test_overflow_hidden_applied_in_css(slide8, shapes_by_id):
    """
    Verify that the parsed data has textInsets for all text shapes,
    so every renderer can apply overflow:hidden + padding correctly.
    """
    text_shapes = [s for s in slide8["shapes"] if s.get("has_text")]
    missing = [s["id"] for s in text_shapes if "textInsets" not in s]
    assert not missing, f"These text shapes are missing textInsets: {missing}"
    print(f"\n✅ All {len(text_shapes)} text shapes on slide 8 have textInsets")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short", "-s"]))
