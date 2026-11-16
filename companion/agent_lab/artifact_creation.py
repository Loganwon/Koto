"""Atomic creation of task outputs; independent of the model/tool dispatcher."""

from pathlib import Path
import uuid
from companion.contracts import CompanionError, ResultUncertain
from companion.file_actions import FileActionProposal, FileActions


def create_basic(broker, name, args):
    if name == "create_spreadsheet" and args["file_name"] in broker.store.get(
        broker.task
    ).get("workbook_schemas", {}):
        raise CompanionError(
            "已登记工作表结构，请使用create_workbook按指定表名和列名生成。"
        )
    required = {
        "create_word": ".docx",
        "create_spreadsheet": ".xlsx",
        "create_presentation": ".pptx",
    }[name]
    if Path(args["file_name"]).suffix.lower() != required:
        raise CompanionError("文件扩展名与输出类型不一致。")
    arguments = {
        k: v for k, v in args.items() if k not in ("action_id", "tables", "draft_id")
    }
    return broker.files.execute(
        FileActionProposal("create_office_file", arguments),
        None,
        broker.permitted,
        lambda kind, value: broker.store.event(broker.task, kind, {"value": value}),
    )


def create_word(broker, args):
    from docx import Document

    destination = broker.files._destination(args["file_name"], {".docx"})
    temporary = destination.parent / (".koto-" + uuid.uuid4().hex + ".docx")
    document = Document()
    document.add_heading(args["title"], 0)
    for s in args["sections"]:
        if s["heading"]:
            document.add_heading(s["heading"], 1)
        document.add_paragraph(s["text"])
    for rows in args["tables"]:
        if not rows or not rows[0] or any((len(row) != len(rows[0]) for row in rows)):
            raise CompanionError("表格每行列数必须一致且非空。")
        table = document.add_table(rows=len(rows), cols=len(rows[0]))
        table.style = "Table Grid"
        for i, row in enumerate(rows):
            for j, text in enumerate(row):
                table.cell(i, j).text = text
    try:
        document.save(temporary)
        check = Document(temporary)
        if len(check.tables) != len(args["tables"]):
            raise CompanionError("表格重新打开校验失败。")
        if not broker.permitted():
            raise CompanionError("已停止，没有发布输出。")
        try:
            FileActions.publish_new(temporary, destination)
        except FileExistsError:
            raise CompanionError("同名文件已经存在，没有覆盖。") from None
        try:
            return FileActions.receipt(
                destination, "create_word", tables=len(check.tables)
            )
        except Exception:
            raise ResultUncertain("文件已发布，但读回失败。") from None
    finally:
        temporary.unlink(missing_ok=True)
