"""Capabilities are selected from the bound editor contract, never user keywords."""

from .cell_edits import LOCAL_FUNCTIONS


def editor_profile(host="word", fragment=None):
    kind = getattr(fragment, "kind", "text")
    cell = host == "excel" and kind == "cell"
    slide = host == "powerpoint"
    return {
        "host": host,
        "unit": "单元格" if cell else "文本框" if slide else "段",
        "kind": kind,
        "label": getattr(fragment, "label", "正文"),
        "metadata": getattr(fragment, "metadata", {}),
        "cell_edit": cell,
        "formula_functions": sorted(LOCAL_FUNCTIONS) if cell else [],
        "text_edit": not cell,
        "write_scope": (
            "仅当前绑定的一个单元格，可写文字、数字、布尔值或本地公式"
            if cell
            else (
                "仅当前绑定的一个幻灯片文本框，不改变版式"
                if slide
                else "仅当前绑定的一个文字片段"
            )
        ),
        "unavailable": [
            "edit_reference_file",
            "edit_other_document",
            "edit_pdf",
            "ocr",
            "save_file",
            "export_file",
            "change_layout",
        ],
    }
