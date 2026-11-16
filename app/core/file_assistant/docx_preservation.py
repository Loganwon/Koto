"""Reject demonstrated OOXML structure loss before replacing an existing source.

This is a loss detector for native structures the HTML editor may omit, not a
claim that equal feature counts establish arbitrary Word layout fidelity.
"""

from __future__ import annotations

import io
import zipfile
from collections import Counter
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocxStructureLossError(RuntimeError):
    def __init__(self, lost_features: list[str]):
        self.lost_features = lost_features
        super().__init__(
            "当前编辑稿未保留原 Word 的结构（"
            + ", ".join(lost_features)
            + "），原文件未覆盖；编辑稿已保留，可另存副本。"
        )


def _inventory(raw: bytes) -> Counter | None:
    try:
        package = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return None
    with package:
        if "word/document.xml" not in package.namelist():
            return None
        counts = Counter()
        roots = {}
        for name in package.namelist():
            if (
                name.startswith("word/")
                and name.endswith(".xml")
                and "/_rels/" not in name
            ):
                roots[name] = ET.fromstring(package.read(name))
        tracked = {
            "ins",
            "del",
            "moveFrom",
            "moveTo",
            "moveFromRangeStart",
            "moveToRangeStart",
            "rPrChange",
            "pPrChange",
            "tblPrChange",
            "trPrChange",
            "tcPrChange",
            "sectPrChange",
        }
        structural = {
            "footnoteReference": "footnote_anchors",
            "endnoteReference": "endnote_anchors",
            "commentRangeStart": "comment_starts",
            "commentRangeEnd": "comment_ends",
            "commentReference": "comment_anchors",
            "drawing": "drawings",
            "pict": "legacy_drawings",
            "fldChar": "field_markers",
            "fldSimple": "fields",
            "sdt": "content_controls",
            "dataBinding": "data_bindings",
            "altChunk": "embedded_content",
            "object": "embedded_objects",
            "txbxContent": "text_boxes",
            "sectPr": "section_properties",
            "titlePg": "first_page_header_mode",
            "evenAndOddHeaders": "even_page_header_mode",
        }
        for name, root in roots.items():
            is_story = name in {
                "word/document.xml",
                "word/footnotes.xml",
                "word/endnotes.xml",
                "word/comments.xml",
            } or name.startswith(("word/header", "word/footer"))
            if not is_story and name != "word/settings.xml":
                continue
            for element in root.iter():
                local = element.tag.rsplit("}", 1)[-1]
                if element.tag.startswith(W):
                    if local in tracked:
                        counts["tracked_changes:" + local] += 1
                    if local in structural:
                        counts[structural[local]] += 1
                    if local == "bookmarkStart":
                        bookmark = element.get(W + "name", "")
                        if bookmark and bookmark != "_GoBack":
                            counts["bookmark:" + bookmark] += 1
                    if local in {"headerReference", "footerReference"}:
                        counts[local + ":" + element.get(W + "type", "default")] += 1
                if local in {"anchor", "chart", "OLEObject", "oMath", "oMathPara"}:
                    counts["native:" + local] += 1
                if local == "graphicData":
                    counts["drawing_kind:" + str(element.get("uri", ""))] += 1
            if name.startswith(("word/header", "word/footer")):
                text = "".join(
                    element.text or "" for element in root.iter(W + "t")
                ).strip()
                if text:
                    counts[
                        (
                            "nonempty_headers"
                            if name.startswith("word/header")
                            else "nonempty_footers"
                        )
                    ] += 1
        # Parts alone can survive as orphans while their body anchors vanish.
        # Check both anchors above and the actual referenced content below.
        for part, tag, label in (
            ("word/footnotes.xml", "footnote", "footnote_content"),
            ("word/endnotes.xml", "endnote", "endnote_content"),
            ("word/comments.xml", "comment", "comment_content"),
        ):
            root = roots.get(part)
            if root is not None:
                for item in root.iter(W + tag):
                    if item.get(W + "type") in {"separator", "continuationSeparator"}:
                        continue
                    text = "".join(
                        element.text or "" for element in item.iter(W + "t")
                    ).strip()
                    if text:
                        counts[label] += 1
        return counts


def _numbering_groups(raw: bytes) -> dict[str, list[list[tuple]]]:
    """Resolve used paragraph numbering, without treating package IDs as meaning.

    A numbering instance is also a restart boundary. Definitions that remain
    orphaned in numbering.xml do not establish that a body list survived.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        names = set(package.namelist())
        styles = {}
        default_style = ""
        if "word/styles.xml" in names:
            for style in ET.fromstring(package.read("word/styles.xml")).iter(
                W + "style"
            ):
                identifier = style.get(W + "styleId", "")
                styles[identifier] = style
                if style.get(W + "type") == "paragraph" and style.get(
                    W + "default"
                ) in {"1", "true", "on"}:
                    default_style = identifier
        numbering = (
            ET.fromstring(package.read("word/numbering.xml"))
            if "word/numbering.xml" in names
            else ET.Element("empty")
        )
        abstracts = {
            item.get(W + "abstractNumId"): item
            for item in numbering.findall(W + "abstractNum")
        }
        numbers = {item.get(W + "numId"): item for item in numbering.findall(W + "num")}

        def value(node, name, default=""):
            child = node.find(W + name) if node is not None else None
            return child.get(W + "val", default) if child is not None else default

        def num_properties(properties):
            num = properties.find(W + "numPr") if properties is not None else None
            return {
                key: value(num, key)
                for key in ("numId", "ilvl")
                if num is not None and num.find(W + key) is not None
            }

        def style_properties(identifier, seen=()):
            if identifier in seen or identifier not in styles:
                return {}
            style = styles[identifier]
            inherited = style_properties(value(style, "basedOn"), (*seen, identifier))
            return {**inherited, **num_properties(style.find(W + "pPr"))}

        def level_properties(num_id, level, seen=()):
            if num_id in seen or num_id not in numbers:
                return {"unresolved": True}
            number = numbers[num_id]
            abstract = abstracts.get(value(number, "abstractNumId"))
            fields = {}
            if abstract is not None:
                linked = value(abstract, "numStyleLink")
                if linked:
                    inherited_id = style_properties(linked).get("numId")
                    if inherited_id:
                        fields.update(
                            level_properties(inherited_id, level, (*seen, num_id))
                        )
                for item in abstract.findall(W + "lvl"):
                    if item.get(W + "ilvl", "0") == level:
                        fields.update({child.tag: child for child in item})
            for override in number.findall(W + "lvlOverride"):
                if override.get(W + "ilvl", "0") != level:
                    continue
                overridden_level = override.find(W + "lvl")
                if overridden_level is not None:
                    fields.update({child.tag: child for child in overridden_level})
                start = override.find(W + "startOverride")
                if start is not None:
                    fields[W + "start"] = start
            return fields

        result = {}
        for name in sorted(names):
            if not (
                name == "word/document.xml"
                or name.startswith(("word/header", "word/footer"))
            ) or not name.endswith(".xml"):
                continue
            groups = {}
            for paragraph in ET.fromstring(package.read(name)).iter(W + "p"):
                properties = paragraph.find(W + "pPr")
                effective = {
                    **style_properties(value(properties, "pStyle", default_style)),
                    **num_properties(properties),
                }
                num_id = effective.get("numId")
                if not num_id or num_id == "0":
                    continue
                level = effective.get("ilvl", "0")
                fields = level_properties(num_id, level)

                def field(key, default):
                    node = fields.get(W + key)
                    return node.get(W + "val", default) if node is not None else default

                legal = fields.get(W + "isLgl")
                legal_mode = legal is not None and legal.get(W + "val", "true") not in {
                    "0",
                    "false",
                    "off",
                }
                font = fields.get(W + "rPr")
                fonts = font.find(W + "rFonts") if font is not None else None
                signature = (
                    level,
                    field("start", "1"),
                    field("numFmt", "decimal"),
                    field("lvlText", ""),
                    field("lvlRestart", level),
                    field("lvlJc", "left"),
                    legal_mode,
                    tuple(sorted(fonts.attrib.items())) if fonts is not None else (),
                    bool(fields.get("unresolved")),
                )
                groups.setdefault(num_id, []).append(signature)
            if groups:
                result[name] = list(groups.values())
        return result


def _numbering_preserved(source: bytes, draft: bytes) -> bool:
    original = _numbering_groups(source)
    edited = _numbering_groups(draft)
    for story, groups in original.items():
        candidates = list(edited.get(story, []))
        for group in groups:
            found = None
            for index, candidate in enumerate(candidates):
                # Appending supported list items is allowed. Each original
                # instance must still have its own equivalent restart scope.
                remaining = iter(candidate)
                if all(any(item == wanted for item in remaining) for wanted in group):
                    found = index
                    break
            if found is None:
                return False
            candidates.pop(found)
    return True


def assert_docx_structure_preserved(source: bytes, draft: bytes) -> None:
    original = _inventory(source)
    if original is None:
        return  # Existing non-OOXML inputs are outside this preservation check.
    try:
        edited = _inventory(draft)
    except (ET.ParseError, zipfile.BadZipFile, KeyError) as exc:
        raise DocxStructureLossError(["invalid_draft_package"]) from exc
    if edited is None:
        raise DocxStructureLossError(["invalid_draft_package"])
    missing = sorted(
        feature for feature, count in original.items() if edited[feature] < count
    )
    if not _numbering_preserved(source, draft):
        missing.append("numbering_semantics")
    if missing:
        raise DocxStructureLossError(missing)
