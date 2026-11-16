"""Component module extracted from docx_parser.py -- god-file refactoring Phase 3."""

from __future__ import annotations


def _unwrap_layout_tables(html: str) -> str:
    """
    Unwrap single-column layout tables into flat content sections.

    Many Word documents (especially resumes) wrap *all* content in a 1-column
    table purely for layout control.  When rendered in the editor these tables
    show ugly borders and break natural page flow.

    Criteria for "layout table":
      - Every row has exactly 1 cell (colspan is OK — still single visual column)
      - No rowspan > 1 (vertical merges indicate a multi-row data table)
      - Table has >= 3 rows (prevents stripping intentional single-row tables)
      - No header row (<th>)

    Each cell's inner HTML is extracted and wrapped in
    ``<div class="koto-layout-section">...</div>`` to preserve grouping.
    Empty cells (spacer rows) become ``<div class="koto-layout-spacer"></div>``.
    """
    try:
        from bs4 import BeautifulSoup, Tag
    except ImportError:
        return html

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    changed = False

    for tbl in tables:
        rows = tbl.find_all("tr", recursive=False)
        if len(rows) < 3:
            continue  # too small — probably a real data table

        # Check: is every row single-cell with no <th>?
        is_layout = True
        for row in rows:
            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) != 1:
                is_layout = False
                break
            cell = cells[0]
            if cell.name == "th":
                is_layout = False
                break
            # colspan is fine (cell just spans full width) — but rowspan > 1
            # means a complex multi-row structure, not pure layout.
            rs = int(cell.get("rowspan", 1) or 1)
            if rs > 1:
                is_layout = False
                break

        if not is_layout:
            continue

        # Skip tables that have visible borders (inline style from rich renderer)
        tbl_style = tbl.get("style", "")
        if "border:" in tbl_style and "border:none" not in tbl_style:
            continue

        fragments = []
        for row in rows:
            cell = row.find(["td", "th"], recursive=False)
            if not cell:
                continue
            inner = cell.decode_contents().strip()
            if not inner or inner in ("<br/>", "<br>", "<br >"):
                div = soup.new_tag("div")
                div["class"] = "koto-layout-spacer"
                fragments.append(div)
            else:
                div = soup.new_tag("div")
                div["class"] = "koto-layout-section"
                # Preserve cell background colour as section background
                cell_style = cell.get("style", "")
                if "background" in cell_style:
                    div["style"] = cell_style
                div.append(BeautifulSoup(inner, "html.parser"))
                fragments.append(div)

        # Replace the <table> in-place
        for frag in reversed(fragments):
            tbl.insert_after(frag)
        tbl.decompose()
        changed = True

    return str(soup) if changed else html
