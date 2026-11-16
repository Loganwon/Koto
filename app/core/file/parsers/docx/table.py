"""Component module extracted from docx_parser.py -- god-file refactoring Phase 3."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _extract_table_styles(docx_path: str) -> list[dict]:
    """
    Extract table cell formatting metadata from a DOCX file using python-docx.

    Returns a list — one entry per table, positionally indexed:
        [
          {  # table 0
            (row, col): {
              "bg":      "RRGGBB" | None,   # cell background fill
              "colspan": int,               # w:gridSpan value
              "rowspan": int,               # logical rowspan (from w:vMerge analysis)
              "bold":    bool,              # header-row bold hint
            },
            ...
          },
          ...  # table 1, table 2, …
        ]

    Falls back to [] silently if python-docx or lxml is unavailable.
    """
    try:
        from docx import Document
        from lxml import etree
    except ImportError:
        return []

    WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def _w(tag: str) -> str:
        return f"{{{WNS}}}{tag}"

    try:
        doc = Document(docx_path)
    except Exception as exc:
        logger.warning("[_extract_table_styles] 无法打开文件: %s", exc)
        return []

    result = []
    for tbl in doc.tables:
        tbl_data: dict = {}

        # ── Column widths from w:tblGrid/w:gridCol (twips → percentages) ──
        # tbl._tbl is the lxml element for the <w:tbl> node.
        tbl_xml = tbl._tbl
        grid_cols = tbl_xml.findall(f".//{_w('gridCol')}")
        if grid_cols:
            raw_widths = []
            for gc in grid_cols:
                w_val = gc.get(_w("w"))
                try:
                    raw_widths.append(max(1, int(w_val or 0)))
                except (ValueError, TypeError):
                    raw_widths.append(1)
            total_w = sum(raw_widths) or 1
            # Store as percentages rounded to 1 decimal; sum ≈ 100 %
            tbl_data["__col_pcts"] = [round(w / total_w * 100, 1) for w in raw_widths]

        for ri, row in enumerate(tbl.rows):
            for ci, cell in enumerate(row.cells):
                tc = cell._tc

                # ── Background colour (w:shd w:fill) ────────────────────
                shd = tc.find(f".//{_w('shd')}")
                bg = None
                if shd is not None:
                    fill = shd.get(_w("fill"))
                    if fill and fill.upper() not in ("AUTO", "FFFFFF", ""):
                        bg = fill.upper()

                # ── Colspan (w:gridSpan) ─────────────────────────────────
                grid_span_el = tc.find(f".//{_w('gridSpan')}")
                colspan = (
                    int(grid_span_el.get(_w("val"), 1))
                    if grid_span_el is not None
                    else 1
                )

                # ── Rowspan: count how many rows below start with w:vMerge (no val attr) ──
                # The first cell of a vertical merge has w:vMerge val="restart";
                # continuation cells have w:vMerge with no val.
                v_merge_el = tc.find(f".//{_w('vMerge')}")
                is_merge_start = (
                    v_merge_el is not None
                    and v_merge_el.get(_w("val"), "") == "restart"
                )
                rowspan = 1
                if is_merge_start:
                    # Count how many rows below continue this merge at the same col
                    for future_ri in range(ri + 1, len(tbl.rows)):
                        if ci >= len(tbl.rows[future_ri].cells):
                            break
                        future_tc = tbl.rows[future_ri].cells[ci]._tc
                        future_vm = future_tc.find(f".//{_w('vMerge')}")
                        if future_vm is not None and future_vm.get(_w("val"), "") == "":
                            rowspan += 1
                        else:
                            break

                # ── Skip continuation vMerge cells (they'll be expressed via rowspan) ──
                is_merge_continuation = (
                    v_merge_el is not None and v_merge_el.get(_w("val"), "") == ""
                )
                if is_merge_continuation:
                    continue  # nothing to write; the HTML rowspan covers it

                tbl_data[(ri, ci)] = {
                    "bg": bg,
                    "colspan": colspan,
                    "rowspan": rowspan,
                }

        result.append(tbl_data)

    return result


def _inject_table_styles(html: str, table_styles: list[dict]) -> str:
    """
    Post-process mammoth's HTML to inject cell background colours, colspan,
    and rowspan attributes that mammoth discards.

    Only modifies cells for which _extract_table_styles() found metadata;
    leaves everything else untouched.
    """
    if not table_styles:
        return html

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    for ti, tbl_tag in enumerate(tables):
        if ti >= len(table_styles):
            break
        style_map = table_styles[ti]
        if not style_map:
            continue

        # ── Inject <colgroup> for proportional column widths ──────────────────
        col_pcts: list[float] = style_map.get("__col_pcts", [])  # type: ignore[assignment]
        if col_pcts and not tbl_tag.find("colgroup"):
            colgroup = soup.new_tag("colgroup")
            for pct in col_pcts:
                col = soup.new_tag("col")
                col["style"] = f"width:{pct:.1f}%"
                colgroup.append(col)
            tbl_tag.insert(0, colgroup)

        rows = tbl_tag.find_all("tr")

        # ── Also inject width% on first-row cells (colgroup may be stripped by
        #    the editor's deserializer; inline td widths survive reliably) ──
        if col_pcts and rows:
            first_row_cells = rows[0].find_all(["td", "th"])
            for ci_col, cell_tag in enumerate(first_row_cells):
                if ci_col < len(col_pcts):
                    existing = cell_tag.get("style", "")
                    w_css = f"width:{col_pcts[ci_col]:.1f}%;"
                    # Don't double-inject
                    if "width:" not in existing:
                        cell_tag["style"] = (existing.rstrip(";") + ";" + w_css).lstrip(
                            ";"
                        )

        for ri, row_tag in enumerate(rows):
            cells = row_tag.find_all(["td", "th"])
            for ci, cell_tag in enumerate(cells):
                meta = style_map.get((ri, ci))
                if not meta:
                    continue

                # colspan / rowspan
                if meta.get("colspan", 1) > 1:
                    cell_tag["colspan"] = str(meta["colspan"])
                if meta.get("rowspan", 1) > 1:
                    cell_tag["rowspan"] = str(meta["rowspan"])

                # background colour
                bg = meta.get("bg")
                if bg:
                    existing = cell_tag.get("style", "")
                    bg_css = f"background-color:#{bg.lower()};"
                    cell_tag["style"] = (existing.rstrip(";") + ";" + bg_css).lstrip(
                        ";"
                    )

    # ── Remove entirely-empty trailing columns ─────────────────────────────
    # The editor sometimes pads rows with phantom empty cells; stripping
    # them here (Python side) avoids reconciler issues on the frontend.
    for tbl_tag in soup.find_all("table"):
        rows = tbl_tag.find_all("tr")
        if not rows:
            continue
        max_cols = max(
            (len(r.find_all(["td", "th"], recursive=False)) for r in rows),
            default=0,
        )
        if max_cols < 2:
            continue
        for ci in range(max_cols - 1, 0, -1):
            all_empty = all(
                len(cells) <= ci
                or (not cells[ci].get_text(strip=True) and not cells[ci].find("img"))
                for cells in (r.find_all(["td", "th"], recursive=False) for r in rows)
            )
            if all_empty:
                for row in rows:
                    cells = row.find_all(["td", "th"], recursive=False)
                    if ci < len(cells):
                        cells[ci].decompose()
            else:
                break

    return str(soup)
