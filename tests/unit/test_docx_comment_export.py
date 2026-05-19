import io
import zipfile
from xml.etree import ElementTree as ET

import pytest


W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _paragraph_text(paragraph) -> str:
    return "".join(node.text or "" for node in paragraph.findall(".//w:t", W_NS))


def _relevant_paragraph_nodes(paragraph) -> list[tuple[str, str]]:
    nodes: list[tuple[str, str]] = []
    for child in list(paragraph):
        local_name = child.tag.split("}", 1)[-1] if "}" in child.tag else child.tag
        if local_name in {"commentRangeStart", "commentRangeEnd"}:
            nodes.append((local_name, ""))
            continue
        if local_name != "r":
            continue
        if child.find(".//w:commentReference", W_NS) is not None:
            nodes.append(("commentReference", ""))
            continue
        text_value = "".join(node.text or "" for node in child.findall(".//w:t", W_NS))
        if text_value:
            nodes.append(("text", text_value))
    return nodes


def test_export_docx_writes_native_comments_xml():
    pytest.importorskip("docx", reason="python-docx 未安装")
    pytest.importorskip("lxml", reason="lxml 未安装")
    pytest.importorskip("bs4", reason="beautifulsoup4 未安装")

    from app.core.file.file_parser import export_docx

    payload = {
        "html": "<p>第一段原文</p><p>第二段保留</p>",
        "comments": [
            {
                "id": "comment-1",
                "author": "审阅人",
                "date": "2026-05-12T10:30:00Z",
                "text": "这里需要进一步说明",
                "anchor_text": "第一段原文",
            }
        ],
    }

    raw = export_docx(payload)

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        assert "word/comments.xml" in names
        comments_xml = archive.read("word/comments.xml").decode("utf-8", errors="ignore")
        document_xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
        rels_xml = archive.read("word/_rels/document.xml.rels").decode("utf-8", errors="ignore")
        content_types_xml = archive.read("[Content_Types].xml").decode("utf-8", errors="ignore")

    assert "这里需要进一步说明" in comments_xml
    assert "审阅人" in comments_xml
    assert "commentRangeStart" in document_xml
    assert "commentReference" in document_xml
    assert "comments.xml" in rels_xml
    assert "/word/comments.xml" in content_types_xml


def test_export_docx_uses_occurrence_hint_for_duplicate_anchor_text():
    pytest.importorskip("docx", reason="python-docx 未安装")
    pytest.importorskip("lxml", reason="lxml 未安装")
    pytest.importorskip("bs4", reason="beautifulsoup4 未安装")

    from app.core.file.file_parser import export_docx

    payload = {
        "html": "<p>重复文本</p><p>重复文本</p>",
        "comments": [
            {
                "id": "comment-duplicate",
                "text": "命中第二段",
                "anchor_text": "重复文本",
                "anchor_occurrence": 1,
            }
        ],
    }

    raw = export_docx(payload)

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        document_tree = ET.fromstring(archive.read("word/document.xml"))

    target_paragraphs = [
        paragraph
        for paragraph in document_tree.findall(".//w:body/w:p", W_NS)
        if _paragraph_text(paragraph) == "重复文本"
    ]

    assert len(target_paragraphs) >= 2
    assert target_paragraphs[0].find(".//w:commentRangeStart", W_NS) is None
    assert target_paragraphs[1].find(".//w:commentRangeStart", W_NS) is not None


def test_export_docx_uses_context_hint_for_duplicate_anchor_text():
    pytest.importorskip("docx", reason="python-docx 未安装")
    pytest.importorskip("lxml", reason="lxml 未安装")
    pytest.importorskip("bs4", reason="beautifulsoup4 未安装")

    from app.core.file.file_parser import export_docx

    payload = {
        "html": "<p>甲重复文本乙</p><p>丙重复文本丁</p>",
        "comments": [
            {
                "id": "comment-context",
                "text": "命中上下文更匹配的段落",
                "anchor_text": "重复文本",
                "anchor_context_before": "丙",
                "anchor_context_after": "丁",
            }
        ],
    }

    raw = export_docx(payload)

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        document_tree = ET.fromstring(archive.read("word/document.xml"))

    target_paragraphs = [
        paragraph
        for paragraph in document_tree.findall(".//w:body/w:p", W_NS)
        if _paragraph_text(paragraph) in {"甲重复文本乙", "丙重复文本丁"}
    ]

    assert len(target_paragraphs) >= 2
    assert target_paragraphs[0].find(".//w:commentRangeStart", W_NS) is None
    assert target_paragraphs[1].find(".//w:commentRangeStart", W_NS) is not None


def test_export_docx_splits_runs_for_exact_comment_offsets():
    pytest.importorskip("docx", reason="python-docx 未安装")
    pytest.importorskip("lxml", reason="lxml 未安装")
    pytest.importorskip("bs4", reason="beautifulsoup4 未安装")

    from app.core.file.file_parser import export_docx

    payload = {
        "html": "<p>甲乙丙丁</p>",
        "comments": [
            {
                "id": "comment-offset",
                "text": "只批注中间两个字",
                "anchor_text": "乙丙",
                "anchor_start_offset": 1,
                "anchor_end_offset": 3,
            }
        ],
    }

    raw = export_docx(payload)

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        document_tree = ET.fromstring(archive.read("word/document.xml"))

    paragraph = next(
        paragraph
        for paragraph in document_tree.findall(".//w:body/w:p", W_NS)
        if _paragraph_text(paragraph) == "甲乙丙丁"
    )

    assert _relevant_paragraph_nodes(paragraph) == [
        ("text", "甲"),
        ("commentRangeStart", ""),
        ("text", "乙丙"),
        ("commentRangeEnd", ""),
        ("commentReference", ""),
        ("text", "丁"),
    ]


def test_exported_docx_comment_roundtrips_anchor_metadata(tmp_path):
    pytest.importorskip("docx", reason="python-docx 未安装")
    pytest.importorskip("lxml", reason="lxml 未安装")
    pytest.importorskip("bs4", reason="beautifulsoup4 未安装")

    from app.core.file.file_parser import _extract_docx_comments, export_docx

    payload = {
        "html": "<p>重复文本</p><p>重复文本</p>",
        "comments": [
            {
                "id": "comment-roundtrip",
                "author": "审阅人",
                "text": "命中第二段",
                "anchor_text": "重复文本",
                "anchor_occurrence": 1,
            }
        ],
    }

    raw = export_docx(payload)
    docx_path = tmp_path / "comment-roundtrip.docx"
    docx_path.write_bytes(raw)

    comments = _extract_docx_comments(str(docx_path))

    assert len(comments) == 1
    comment = comments[0]
    assert comment["author"] == "审阅人"
    assert comment["text"] == "命中第二段"
    assert comment["anchor_text"] == "重复文本"
    assert comment["anchor_occurrence"] == 1
    assert comment["anchor_start_offset"] == len("重复文本\n")
    assert comment["anchor_end_offset"] == len("重复文本\n重复文本")
    assert comment["anchor_context_before"].endswith("重复文本\n")
    assert comment["anchor_context_after"].startswith("\n")


def test_extract_docx_comments_reads_modern_comment_metadata(tmp_path):
        from app.core.file.file_parser import _extract_docx_comments

        docx_path = tmp_path / "modern-comments.docx"
        with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                        "word/comments.xml",
                        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                        xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">
    <w:comment w:id="0" w:author="甲作者" w:initials="甲" w:date="2026-05-16T10:00:00Z" w14:paraId="00AA11">
        <w:p><w:r><w:t>主批注</w:t></w:r></w:p>
    </w:comment>
    <w:comment w:id="1" w:author="乙作者" w:initials="乙" w:date="2026-05-16T10:01:00Z" w14:paraId="00BB22">
        <w:p><w:r><w:t>回复批注</w:t></w:r></w:p>
    </w:comment>
</w:comments>""",
                )
                archive.writestr(
                        "word/document.xml",
                        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:body>
        <w:p>
            <w:r><w:t>正文开始</w:t></w:r>
            <w:commentRangeStart w:id="0"/>
            <w:r><w:t>批注锚点</w:t></w:r>
            <w:commentRangeEnd w:id="0"/>
            <w:r><w:commentReference w:id="0"/></w:r>
        </w:p>
    </w:body>
</w:document>""",
                )
                archive.writestr(
                        "word/commentsExtended.xml",
                        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w14:commentExs xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">
    <w14:commentEx w14:paraId="00AA11" w14:done="1"/>
    <w14:commentEx w14:paraId="00BB22" w14:paraIdParent="00AA11"/>
</w14:commentExs>""",
                )
                archive.writestr(
                        "word/commentsIds.xml",
                        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w16cid:commentsIds xmlns:w16cid="http://schemas.microsoft.com/office/word/2016/wordml/cid">
    <w16cid:commentId w16cid:paraId="00AA11" w16cid:durableId="durable-main"/>
    <w16cid:commentId w16cid:paraId="00BB22" w16cid:durableId="durable-reply"/>
</w16cid:commentsIds>""",
                )

        comments = _extract_docx_comments(str(docx_path))

        assert len(comments) == 2
        assert comments[0]["initials"] == "甲"
        assert comments[0]["para_id"] == "00AA11"
        assert comments[0]["durable_id"] == "durable-main"
        assert comments[0]["done"] is True
        assert comments[0]["anchor_text"] == "批注锚点"
        assert comments[1]["initials"] == "乙"
        assert comments[1]["parent_para_id"] == "00AA11"
        assert comments[1]["parent_id"] == "0"
        assert comments[1]["durable_id"] == "durable-reply"


def test_extract_docx_revisions_reads_native_tracked_changes(tmp_path):
        from app.core.file.file_parser import _extract_docx_revisions

        docx_path = tmp_path / "native-revisions.docx"
        with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                        "word/document.xml",
                        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:body>
        <w:p>
            <w:r><w:t>前文</w:t></w:r>
            <w:del w:id="1" w:author="审阅人" w:date="2026-05-17T08:00:00Z"><w:r><w:delText>旧句子</w:delText></w:r></w:del>
            <w:ins w:id="2" w:author="审阅人" w:date="2026-05-17T08:00:00Z"><w:r><w:t>新句子</w:t></w:r></w:ins>
            <w:r><w:t>后文</w:t></w:r>
        </w:p>
        <w:p>
            <w:r><w:t>第二段</w:t></w:r>
            <w:ins w:id="3" w:author="另一个审阅人" w:date="2026-05-17T09:00:00Z"><w:r><w:t>补充</w:t></w:r></w:ins>
        </w:p>
    </w:body>
</w:document>""",
                )

        revisions = _extract_docx_revisions(str(docx_path))

        assert len(revisions) == 2
        assert revisions[0]["action"] == "replace"
        assert revisions[0]["original_text"] == "旧句子"
        assert revisions[0]["proposed_text"] == "新句子"
        assert revisions[0]["author"] == "审阅人"
        assert revisions[0]["read_only"] is True
        assert revisions[0]["apply_disabled"] is True
        assert revisions[1]["action"] == "insert"
        assert revisions[1]["original_text"] == ""
        assert revisions[1]["proposed_text"] == "补充"


def test_parse_docx_renders_native_tracked_changes_inline_markup(tmp_path):
        pytest.importorskip("docx", reason="python-docx 未安装")

        from docx import Document
        from app.core.file.file_parser import parse_docx

        docx_path = tmp_path / "native-revisions-inline.docx"
        base_doc = Document()
        base_doc.add_paragraph("占位")
        base_doc.save(docx_path)

        replacement_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:body>
        <w:p>
            <w:r><w:t>前文</w:t></w:r>
            <w:del w:id="1" w:author="审阅人" w:date="2026-05-17T08:00:00Z"><w:r><w:delText>旧句子</w:delText></w:r></w:del>
            <w:ins w:id="2" w:author="审阅人" w:date="2026-05-17T08:00:00Z"><w:r><w:t>新句子</w:t></w:r></w:ins>
            <w:r><w:t>后文</w:t></w:r>
        </w:p>
    <w:sectPr>
        <w:pgSz w:w="12240" w:h="15840"/>
        <w:pgMar w:top="1440" w:right="1800" w:bottom="1440" w:left="1800" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
    </w:body>
</w:document>"""

        with zipfile.ZipFile(docx_path, "r") as archive:
                existing = {name: archive.read(name) for name in archive.namelist()}

        with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, raw in existing.items():
                        archive.writestr(name, replacement_xml if name == "word/document.xml" else raw)

        parsed = parse_docx(str(docx_path))
        html = str(parsed.get("html") or "")

        assert 'data-koto-review-id="docx-revision-1"' in html
        assert 'data-koto-review-action="replace"' in html
        assert 'koto-docx-track-change-delete' in html
        assert 'koto-docx-track-change-insert' in html
        assert '旧句子' in html
        assert '新句子' in html