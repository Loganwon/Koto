"""Reference parsers. Nothing here executes document instructions or macros."""

from pathlib import Path
from io import BytesIO
import zipfile
import xml.etree.ElementTree as ET
import posixpath

from .contracts import CompanionError
from .reading import TextSnapshot

SUPPORTED = {".txt", ".md", ".csv", ".tsv", ".json", ".docx", ".xlsx", ".pptx", ".pdf"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _xml_text(node):
    # Preserve paragraph/table order, including nested tables and cell boundaries.
    if node.tag == W + "t":
        return node.text or ""
    if node.tag == W + "tab":
        return "\t"
    if node.tag in (W + "br", W + "cr"):
        return "\n"
    if node.tag == W + "del":
        return ""  # Visible current version, not deleted revision content.
    content = "".join(_xml_text(child) for child in node)
    if node.tag == W + "p":
        content += "\n"
    if node.tag == W + "tc":
        content += "\t"
    return content


def _docx(path):
    blocks, areas = [], []
    with zipfile.ZipFile(path) as package:
        xml_files = [
            n
            for n in package.namelist()
            if n == "word/document.xml"
            or n.startswith(("word/header", "word/footer"))
            and n.endswith(".xml")
            or n in ("word/footnotes.xml", "word/endnotes.xml", "word/comments.xml")
        ]
        if sum(package.getinfo(n).file_size for n in xml_files) > 64 * 1024 * 1024:
            raise CompanionError("文档解压内容过大，本次未读取。")
        for name in sorted(xml_files, key=lambda n: (n != "word/document.xml", n)):
            value = _xml_text(ET.fromstring(package.read(name)))
            blocks.append(f"[{name}]\n{value}")
            areas.append(name)
    return TextSnapshot(
        path.name, "\n".join(blocks), tuple(areas), ("图片未 OCR；嵌入对象未解析",)
    )


def _xlsx(path):
    import openpyxl

    with zipfile.ZipFile(path) as package:
        if sum(info.file_size for info in package.infolist()) > 64 * 1024 * 1024:
            raise CompanionError("表格解压内容过大，本次未读取。")

    # Read-only worksheet generators can outlive Workbook.close(). Reading from
    # memory prevents their ZipExtFile handles from locking the source file on
    # Windows after a successful verification / atomic file publication.
    raw = path.read_bytes()
    formulas = openpyxl.load_workbook(BytesIO(raw), read_only=True, data_only=False)
    values = openpyxl.load_workbook(BytesIO(raw), read_only=True, data_only=True)
    lines, areas = [], []
    try:
        for sheet in formulas:
            areas.append(sheet.title)
            lines.append(f"[工作表 {sheet.title} · {sheet.sheet_state}]")
            if sheet.max_row * sheet.max_column > 1000000:
                raise CompanionError("工作表范围超过本版读取上限，未标记为读取完成。")
            cached = values[sheet.title]
            for row, computed in zip(sheet.iter_rows(), cached.iter_rows()):
                for cell, result in zip(row, computed):
                    if cell.value is not None:
                        text = str(cell.value)
                        if cell.data_type == "f":
                            text += f" [缓存结果: {result.value}]"
                        lines.append(f"{sheet.title}!{cell.coordinate}\t{text}")
        return TextSnapshot(
            path.name, "\n".join(lines), tuple(areas), ("图片、图表和嵌入对象未解析",)
        )
    finally:
        formulas.close()
        values.close()


def _pptx(path):
    p = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    r = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    blocks, coverage = [], []
    with zipfile.ZipFile(path) as package:
        if sum(item.file_size for item in package.infolist()) > 64 * 1024 * 1024:
            raise CompanionError("演示稿解压内容过大，本次未读取。")

        def relations(part):
            relpath = posixpath.join(
                posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"
            )
            if relpath not in package.namelist():
                return {}
            result = {}
            for item in ET.fromstring(package.read(relpath)):
                if item.get("TargetMode") == "External":
                    continue
                target = item.get("Target", "")
                name = posixpath.normpath(
                    target.lstrip("/")
                    if target.startswith("/")
                    else posixpath.join(posixpath.dirname(part), target)
                )
                if name.startswith("ppt/"):
                    result[item.get("Id")] = (name, item.get("Type", ""))
            return result

        def paragraphs(part):
            tree = ET.fromstring(package.read(part))
            return "\n".join(
                "".join(child.text or "" for child in node.iter(a + "t"))
                for node in tree.iter(a + "p")
            )

        presentation = "ppt/presentation.xml"
        links = relations(presentation)
        slides = ET.fromstring(package.read(presentation)).find(p + "sldIdLst")
        if slides is None:
            return TextSnapshot(path.name, "", (), ("演示稿没有幻灯片",))
        for number, slide in enumerate(slides, 1):
            name, _ = links[slide.get(r + "id")]
            coverage.append(f"第{number}页正文及表格文字")
            blocks.append(f"[第{number}页]\n" + paragraphs(name))
            for note, kind in relations(name).values():
                if kind.endswith("/notesSlide"):
                    coverage.append(f"第{number}页备注")
                    blocks.append(f"[第{number}页备注]\n" + paragraphs(note))
    return TextSnapshot(
        path.name,
        "\n".join(blocks),
        tuple(coverage),
        ("图片未OCR；图表、SmartArt、嵌入对象及母版未解析",),
    )


def parse_file(path: Path):
    try:
        if path.stat().st_size > 32 * 1024 * 1024:
            raise CompanionError("参考文件超过 32 MB，本次未读取。")
        suffix = path.suffix.lower()
        if suffix == ".docx":
            return _docx(path)
        if suffix == ".xlsx":
            return _xlsx(path)
        if suffix == ".pptx":
            return _pptx(path)
        if suffix == ".pdf":
            from pypdf import PdfReader

            document = PdfReader(path)
            if document.is_encrypted:
                raise CompanionError("PDF 已加密，请先解密。")
            pages, missing = [], []
            for number, page in enumerate(document.pages, 1):
                text = page.extract_text() or ""
                pages.append(f"[第 {number} 页]\n{text}")
                if not text.strip():
                    missing.append(f"第 {number} 页无可提取文字（可能需要 OCR）")
            return TextSnapshot(
                path.name,
                "\n".join(pages),
                tuple(f"第 {i+1} 页" for i in range(len(pages))),
                tuple(missing) + ("图片未 OCR",),
            )
        if suffix in SUPPORTED:
            data = path.read_bytes()
            try:
                text = data.decode("utf-8-sig")
            except UnicodeError:
                text = data.decode("gb18030")
            return TextSnapshot(path.name, text)
        raise CompanionError(
            "该格式暂不支持内容读取，请使用 DOCX、XLSX、PPTX、PDF 或文本文件。"
        )
    except CompanionError:
        raise
    except Exception:
        raise CompanionError("参考文件解析失败，未将其标记为读取完成。") from None
