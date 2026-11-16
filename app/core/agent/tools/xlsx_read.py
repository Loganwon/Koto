"""Domain module - XLSX read tools."""

from __future__ import annotations


def _read_xlsx_sheet_window(
    path: str,
    *,
    max_chars: int,
    sheet_index: int,
) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet_names = list(wb.sheetnames or [])
        if not sheet_names:
            return ""
        safe_index = max(0, min(int(sheet_index or 0), len(sheet_names) - 1))
        ws = wb[sheet_names[safe_index]]
        parts = [f"[Sheet {safe_index + 1}: {ws.title}]"]
        total = len(parts[0])
        for row_index, row in enumerate(ws.iter_rows(values_only=True), start=1):
            values = ["" if value is None else str(value) for value in row]
            if not any(value.strip() for value in values):
                continue
            line = f"R{row_index}: " + " | ".join(values)
            parts.append(line)
            total += len(line)
            if total >= max_chars:
                break
        return "\n".join(parts)
    finally:
        wb.close()
