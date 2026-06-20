# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import ast
import io
import json
import os
import re
from typing import Any, Dict, List
import zipfile


def _plain_text_to_docx_paragraphs(content: str) -> List[Dict[str, str]]:
    paragraphs: List[Dict[str, str]] = []
    for raw_line in str(content or "").splitlines():
        line = raw_line.strip()
        if not line or re.fullmatch(r"[-*_]{3,}", line):
            continue
        style = "Normal"
        text = line
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = min(len(heading_match.group(1)), 3)
            style = f"Heading {level}"
            text = heading_match.group(2).strip()
        else:
            bullet_match = re.match(r"^[-*•]\s+(.+)$", line)
            if bullet_match:
                style = "List Bullet"
                text = bullet_match.group(1).strip()
        text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
        text = re.sub(r"__([^_\n]+)__", r"\1", text)
        if text:
            paragraphs.append({"text": text, "style": style})
    if not paragraphs and str(content or "").strip():
        paragraphs.append({"text": str(content).strip(), "style": "Normal"})
    return paragraphs


def _docx_xml_escape(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _normalize_docx_paragraphs(paragraphs: Any) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    raw_items = paragraphs if isinstance(paragraphs, list) else []
    for item in raw_items:
        if isinstance(item, dict):
            text = str(item.get("text") or "")
            style = str(item.get("style") or "").strip()
        else:
            text = str(item or "")
            style = ""
        normalized.append({"text": text, "style": style})
    return normalized


def _parse_loose_docx_paragraph_items(text: str) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    pattern = re.compile(
        r"\{\s*['\"]text['\"]\s*:\s*['\"](?P<text>.*?)['\"]\s*,\s*"
        r"['\"]style['\"]\s*:\s*['\"](?P<style>[^'\"]*)['\"]\s*\}",
        re.DOTALL,
    )
    for match in pattern.finditer(str(text or "")):
        value = match.group("text")
        style = match.group("style")
        value = value.replace('\\"', '"').replace("\\'", "'")
        value = value.replace("\\n", "\n").replace("\\t", "\t")
        normalized.append({"text": value, "style": style})
    return normalized


def _coerce_docx_paragraphs_for_write(paragraphs: Any) -> List[Dict[str, str]]:
    if isinstance(paragraphs, str):
        text = paragraphs.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            return _normalize_docx_paragraphs(parsed)
        except json.JSONDecodeError:
            pass
        try:
            parsed = ast.literal_eval(text)
            return _normalize_docx_paragraphs(parsed)
        except Exception:
            loose_items = _parse_loose_docx_paragraph_items(text)
            if loose_items:
                return loose_items
            return _plain_text_to_docx_paragraphs(text)
    if isinstance(paragraphs, list):
        return _normalize_docx_paragraphs(paragraphs)
    if paragraphs is None:
        return []
    return _plain_text_to_docx_paragraphs(str(paragraphs))


def _minimal_docx_style_id(style: str) -> str:
    normalized = str(style or "").strip().lower().replace("_", " ")
    if normalized in {"heading 1", "title"}:
        return "Heading1"
    if normalized == "heading 2":
        return "Heading2"
    if normalized == "heading 3":
        return "Heading3"
    if normalized in {"list bullet", "bullet"}:
        return "ListBullet"
    return ""


def _minimal_docx_paragraph_xml(item: Dict[str, str]) -> str:
    text = _docx_xml_escape(item.get("text") or "")
    style_id = _minimal_docx_style_id(item.get("style") or "")
    style_xml = f'<w:pPr><w:pStyle w:val="{style_id}"/></w:pPr>' if style_id else ""
    return f'<w:p>{style_xml}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def _minimal_docx_styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="2"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/></w:style>
</w:styles>"""


def _minimal_docx_document_xml(paragraphs: List[Dict[str, str]]) -> str:
    body = "".join(_minimal_docx_paragraph_xml(item) for item in paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body>'
        "</w:document>"
    )


def _minimal_docx_package_bytes(
    paragraphs: List[Dict[str, str]], existing_path: str = ""
) -> bytes:
    document_xml = _minimal_docx_document_xml(paragraphs)
    existing_entries: Dict[str, bytes] = {}
    if existing_path and os.path.exists(existing_path):
        try:
            with zipfile.ZipFile(existing_path, "r") as existing_docx:
                for name in existing_docx.namelist():
                    existing_entries[name] = existing_docx.read(name)
                current_document = existing_entries.get(
                    "word/document.xml", b""
                ).decode("utf-8", errors="replace")
                insert_xml = "".join(
                    _minimal_docx_paragraph_xml(item) for item in paragraphs
                )
                body_end = current_document.rfind("</w:body>")
                sect_start = current_document.rfind("<w:sectPr")
                insert_at = (
                    sect_start if sect_start > 0 and sect_start < body_end else body_end
                )
                if insert_at > 0:
                    document_xml = (
                        current_document[:insert_at]
                        + insert_xml
                        + current_document[insert_at:]
                    )
        except Exception:
            existing_entries = {}

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as docx_zip:

        def write_default(name: str, data: str | bytes) -> None:
            raw = data.encode("utf-8") if isinstance(data, str) else data
            docx_zip.writestr(name, raw)

        if existing_entries:
            overwritten_entries = {
                "[Content_Types].xml",
                "_rels/.rels",
                "word/_rels/document.xml.rels",
                "word/document.xml",
                "word/styles.xml",
            }
            for name, raw in existing_entries.items():
                if name in overwritten_entries:
                    continue
                docx_zip.writestr(name, raw)
        write_default(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>""",
        )
        write_default(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        write_default(
            "word/_rels/document.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""",
        )
        write_default("word/document.xml", document_xml)
        write_default("word/styles.xml", _minimal_docx_styles_xml())
    return buffer.getvalue()
