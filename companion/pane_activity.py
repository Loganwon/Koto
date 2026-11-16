"""Small, public operation receipts for the native task pane; never model reasoning."""

_TOOL_TITLES = {
    "read_current_document": "读取当前文档",
    "search_current_document": "查找文档内容",
    "read_fragment": "读取目标段落",
    "read_document": "读取文档内容",
    "inspect_source": "检查参考资料",
    "read_source": "读取参考资料",
    "query_data": "查询并核对表格数据",
    "apply_edit": "写回原文并读回核对",
    "preserve_fragment": "保留原文",
    "create_word": "生成 Word 文档",
    "create_excel": "生成 Excel 表格",
    "create_spreadsheet": "生成 Excel 表格",
    "create_powerpoint": "生成 PowerPoint 演示文稿",
    "create_presentation": "生成 PowerPoint 演示文稿",
    "create_pdf": "生成 PDF",
    "complete_task": "核对任务交付",
}


def public_activity(event):
    """Project completed tool events, exposing no arguments or returned document data."""
    kind = event.get("kind")
    if kind not in ("tool_result", "tool_error", "tool_uncertain"):
        return None
    body = event.get("body") or {}
    title = _TOOL_TITLES.get(body.get("tool"))
    if not title:
        return None
    status = (
        "uncertain" if kind == "tool_uncertain"
        else "error" if kind == "tool_error" or body.get("ok") is not True
        else "done"
    )
    return {"id": event["seq"], "title": title, "status": status}
