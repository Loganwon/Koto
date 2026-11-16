"""Verified file results, independent of the current fragment's text edits."""

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import uuid
from urllib.parse import unquote, urlsplit

from .contracts import CompanionError, OperationCancelled, ResultUncertain


@dataclass(frozen=True)
class FileActionProposal:
    action: str
    arguments: dict


def definition(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


FILE_TOOLS = [
    definition(
        "save_current_document",
        "Save the bound native document at its existing path. No Save As or new dialogs. Available only when this host supports it.",
        {},
        [],
    ),
    definition(
        "export_current_pdf",
        "Export the bound native document as a new PDF in the chosen workspace; no overwrite. Returns a verified file receipt, not a text edit.",
        {"file_name": {"type": "string", "minLength": 5, "maxLength": 120}},
        ["file_name"],
    ),
    definition(
        "create_office_file",
        "Create a new DOCX, PPTX or XLSX in the chosen workspace. Never changes the current document or overwrites an existing file. DOCX/PPTX use sections; XLSX uses rows of scalar values. Keep each slide concise; no images, charts or arbitrary code.",
        {
            "file_name": {"type": "string", "minLength": 6, "maxLength": 120},
            "title": {"type": "string", "minLength": 1, "maxLength": 100},
            "sections": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string", "maxLength": 100},
                        "text": {"type": "string", "maxLength": 800},
                    },
                    "required": ["heading", "text"],
                    "additionalProperties": False,
                },
            },
            "rows": {
                "type": "array",
                "maxItems": 200,
                "items": {"type": "array", "maxItems": 26, "items": {}},
            },
        },
        ["file_name", "title"],
    ),
]


class FileActions:
    @staticmethod
    def publish_new(temporary, destination):
        """Publish exclusively on the same volume, including Windows without hard links."""
        if os.name == "nt":
            # Windows rename fails if the destination exists; os.replace would overwrite it.
            os.rename(temporary, destination)
        else:
            os.link(temporary, destination)

    def __init__(self, workspace, documents):
        self.workspace, self.documents = workspace, documents

    def definitions(self):
        caps = (
            self.documents.file_capabilities()
            if hasattr(self.documents, "file_capabilities")
            else {}
        )
        opened = self.workspace.tree()["root"] is not None
        names = {"create_office_file"} if opened else set()
        if caps.get("save_document"):
            names.add("save_current_document")
        if opened and caps.get("export_pdf"):
            names.add("export_current_pdf")
        return [item for item in FILE_TOOLS if item["function"]["name"] in names]

    def _destination(self, name, extensions):
        if (
            not isinstance(name, str)
            or len(name) > 120
            or not name.strip()
            or name != name.strip()
            or any(c in name for c in '/\\<>:"|?*')
            or name.startswith(".")
            or name.endswith((".", " "))
            or Path(name).suffix.lower() not in extensions
        ):
            raise CompanionError(
                "请提供工作文件夹中的新文件名，使用对应扩展名，不包含路径。"
            )
        if name.split(".")[0].upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *("COM" + str(i) for i in range(1, 10)),
            *("LPT" + str(i) for i in range(1, 10)),
        }:
            raise CompanionError("这个文件名不能用于保存。")
        root = self.workspace.tree()["root"]
        if not root:
            raise CompanionError("请先打开存放结果的工作文件夹。")
        path = Path(root) / name
        if path.exists() or path.is_symlink():
            raise CompanionError("同名文件已经存在，请换一个文件名；没有覆盖原文件。")
        return path

    @staticmethod
    def receipt(path, action, **extra):
        raw = path.read_bytes()
        if not raw:
            raise CompanionError("输出文件为空，不能标记完成。")
        return {
            "action": action,
            "name": path.name,
            "path": str(path),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "verified": True,
            **extra,
        }

    def execute(self, proposal, target, permitted, progress):
        if proposal.action not in {t["function"]["name"] for t in self.definitions()}:
            raise CompanionError("当前宿主或工作文件夹没有提供这项文件能力。")
        from .harness import validate

        schema = next(
            t["function"]["parameters"]
            for t in FILE_TOOLS
            if t["function"]["name"] == proposal.action
        )
        validate(proposal.arguments, schema)
        if not permitted():
            raise OperationCancelled("已停止，没有执行文件操作。")
        if proposal.action == "save_current_document":
            result = self.documents.call(
                "save_document", target.id, permitted=permitted
            )
            if (
                not isinstance(result, dict)
                or result.get("saved") is not True
                or result.get("path") != target.path
            ):
                raise ResultUncertain(
                    "宿主未确认原文件保存结果，请检查原文档；不会自动重试。"
                )
            value = unquote(target.path)
            if value.startswith("file://"):
                value = urlsplit(value).path
                if os.name == "nt" and len(value) > 2 and value[2] == ":":
                    value = value[1:]
            path = Path(value)
            if path.is_file():
                return self.receipt(path, proposal.action, saved=True)
            if urlsplit(target.path).scheme not in ("https", "http"):
                raise ResultUncertain(
                    "宿主报告已保存，但未找到原路径下的文件；请检查文档，不会自动重试。"
                )
            return {
                "action": proposal.action,
                "name": target.name,
                "path": target.path,
                "saved": True,
                "verified": True,
                "verification": "native_save_acknowledged",
                "disk_verified": False,
            }
        args = proposal.arguments
        destination = self._destination(
            args["file_name"],
            (
                {".pdf"}
                if proposal.action == "export_current_pdf"
                else {".docx", ".pptx", ".xlsx"}
            ),
        )
        generation = self.workspace.tree()["generation"]
        temporary = destination.parent / (
            ".koto-" + uuid.uuid4().hex + destination.suffix
        )
        uncertain = False
        try:
            if proposal.action == "export_current_pdf":
                try:
                    self.documents.call(
                        "export_pdf", target.id, str(temporary), permitted=permitted
                    )
                except ResultUncertain:
                    uncertain = True
                    raise
                from pypdf import PdfReader

                if not PdfReader(temporary).pages:
                    raise CompanionError("导出的 PDF 没有可读页面，未标记完成。")
            else:
                self._create(temporary, args, progress)
                from .file_readers import parse_file

                if not parse_file(temporary).text.strip():
                    raise CompanionError("新文件没有可验证的内容。")
            if not permitted():
                raise OperationCancelled("已停止，没有发布新文件。")
            if generation != self.workspace.tree()["generation"]:
                raise CompanionError("工作文件夹已切换，没有发布旧任务的结果。")
            # Publish within one directory without replacing a concurrently created file.
            try:
                self.publish_new(temporary, destination)
            except FileExistsError:
                raise CompanionError("同名文件已出现，没有覆盖。") from None
            try:
                return self.receipt(
                    destination, proposal.action, file_id=destination.name
                )
            except Exception:
                raise ResultUncertain(
                    "输出文件已发布，但无法读取校验结果；请检查文件，不会自动重试。"
                ) from None
        finally:
            if not uncertain:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _create(path, args, progress):
        sections, rows = args.get("sections", []), args.get("rows", [])
        if path.suffix.lower() == ".docx":
            if not sections or rows:
                raise CompanionError("Word 文件需要正文分节，不接受单元格数据。")
            from docx import Document

            document = Document()
            document.add_heading(args["title"], 0)
            for i, section in enumerate(sections):
                progress("file_generation", f"第 {i + 1} / {len(sections)} 节")
                if section["heading"]:
                    document.add_heading(section["heading"], 1)
                document.add_paragraph(section["text"])
            document.save(path)
        elif path.suffix.lower() == ".pptx":
            if not sections or rows:
                raise CompanionError("演示文件需要简短的逐页内容，不接受单元格数据。")
            from pptx import Presentation
            from pptx.util import Inches, Pt

            presentation = Presentation()
            presentation.slide_width, presentation.slide_height = Inches(
                13.333
            ), Inches(7.5)
            presentation.core_properties.title = args["title"]
            for i, section in enumerate(sections):
                progress("file_generation", f"第 {i + 1} / {len(sections)} 页")
                slide = presentation.slides.add_slide(presentation.slide_layouts[5])
                title_shape = slide.shapes.title
                title_shape.left, title_shape.top = Inches(0.7), Inches(0.5)
                title_shape.width, title_shape.height = Inches(12), Inches(1)
                title = title_shape.text_frame
                title.paragraphs[0].text = section["heading"] or args["title"]
                title.paragraphs[0].font.size = Pt(28)
                body = slide.shapes.add_textbox(
                    Inches(0.7), Inches(1.8), Inches(12), Inches(5)
                ).text_frame
                body.word_wrap = True
                body.text = section["text"]
                for paragraph in body.paragraphs:
                    paragraph.font.size = Pt(18 if len(section["text"]) <= 350 else 14)
            presentation.save(path)
        else:
            if not rows or sections:
                raise CompanionError("Excel 文件需要二维行列数据。")
            from openpyxl import Workbook

            book = Workbook()
            try:
                sheet = book.active
                sheet.title = "数据"
                for row in rows:
                    for value in row:
                        if type(value) in (int, float) and math.isfinite(value):
                            from .cell_edits import cell_proposal

                            cell_proposal("number", str(value), "保留数值精度")
                        if (
                            type(value) not in (str, int, float, bool, type(None))
                            or isinstance(value, float)
                            and not math.isfinite(value)
                            or isinstance(value, str)
                            and (len(value) > 2000 or value.startswith("="))
                        ):
                            raise CompanionError(
                                "新表格仅接受普通文字、有限数字和布尔值，不能隐式执行公式。"
                            )
                    sheet.append(row)
                book.save(path)
            finally:
                book.close()
