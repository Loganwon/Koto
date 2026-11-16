#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Word Track Changes 修订模式实现（改进版）
在文档中插入可以 accept/decline 的修改建议

改进点：
1. 保留原有格式（粗体、斜体、颜色等）
2. 支持同一段落内多处修改
3. 更精确的文本定位
4. 详细的成功/失败统计
"""

import logging
import os
import re
import shutil
import zipfile
from datetime import datetime
from typing import Any, Dict, List

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from lxml import etree

logger = logging.getLogger(__name__)

_COMMENTS_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _normalize_text_for_match(text: str) -> str:
    """Normalize AI-returned text so it matches the plain text stored in Word para.text.

    format_for_ai() decorates paragraphs with Markdown symbols (##, -, >, **...)
    that are NOT present in the Word document's para.text.  When the AI echoes those
    symbols back in the '原文片段' field, exact matching fails silently.

    Normalization steps (safe to apply to both original and modified text):
      1. Unicode NFC  – prevent composed/decomposed CJK mismatch
      2. Strip leading block-level Markdown (headings, lists, blockquotes)
      3. Remove inline bold / italic markers anywhere in the string
      4. Strip the image-caption suffix added by format_for_ai
      5. Normalize all Unicode whitespace variants to a regular space
      6. Collapse runs of whitespace to a single space
    """
    import unicodedata

    t = unicodedata.normalize("NFC", text)
    # Block-level prefixes (only at string start)
    t = re.sub(r"^#{1,6}[ \t]+", "", t)  # ## Heading
    t = re.sub(r"^[-*+][ \t]+", "", t)  # - list item
    t = re.sub(r"^\d+\.[ \t]+", "", t)  # 1. list item
    t = re.sub(r"^>[ \t]+", "", t)  # > blockquote
    # Inline bold / italic (anywhere in string)
    t = re.sub(r"\*\*([^*]+?)\*\*", r"\1", t)  # **bold**
    t = re.sub(r"\*([^*]+?)\*", r"\1", t)  # *italic*
    t = re.sub(r"`([^`]+?)`", r"\1", t)  # `code`
    # Image caption suffix from format_for_ai: "  *(图片，无法直接编辑文本)*"
    t = re.sub(r"\s*\*\([^)]*图片[^)]*\)\*\s*$", "", t)
    # Unicode spaces → regular space
    t = re.sub(r"[\u00a0\u3000\u2009\u2003\u200b]", " ", t)
    # Collapse whitespace runs
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


# Keep old name as alias so any external call still works
_strip_md_formatting = _normalize_text_for_match


def _find_para_with_text(
    all_paragraphs,
    original_text: str,
) -> tuple:
    """Return (para, effective_text) for the first paragraph containing original_text.

    Uses a two-level search:
      Level 1 – exact match against para.text (fastest, no transformation)
      Level 2 – normalized original vs raw para.text
               (handles ## / - / ** markers echoed by AI)

    Returns (None, '') if no paragraph found at any level.
    """
    if not original_text:
        return None, ""

    norm = _normalize_text_for_match(original_text)
    candidates = [original_text]
    if norm and norm != original_text:
        candidates.append(norm)

    for candidate in candidates:
        for para in all_paragraphs:
            if candidate in para.text:
                return para, candidate

    return None, ""


from ._comments import _TrackChangesCommentMixin
from ._tracking import _TrackChangesTrackingMixin


class TrackChangesEditor(_TrackChangesCommentMixin, _TrackChangesTrackingMixin):
    """Apply tracked changes and comments to DOCX files."""

    @staticmethod
    def _esc(text: str) -> str:
        """转义 XML"""
        if not text:
            return ""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    def apply_comment_changes(
        self, file_path: str, annotations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Write Word comments only (no track-changes) into an existing DOCX.

        Returns {"success": bool, "applied": int, "failed": int, "total": int}.
        """
        try:
            # Continue the comment id counter from previously written comments
            # so repeated writes do not collide on w:id values.
            try:
                with zipfile.ZipFile(file_path, "r") as archive:
                    if "word/comments.xml" in archive.namelist():
                        existing_ids = [
                            int(node.get("{%s}id" % _COMMENTS_W_NS) or 0)
                            for node in self._existing_comment_elements(
                                archive.read("word/comments.xml")
                            )
                            if (node.get("{%s}id" % _COMMENTS_W_NS) or "").isdigit()
                        ]
                        if existing_ids:
                            self.change_id = max(existing_ids)
            except (OSError, zipfile.BadZipFile):
                pass

            doc = Document(file_path)
            comment_items = []
            for anno in annotations or []:
                original = str(
                    anno.get("原文片段")
                    or anno.get("anchor_text")
                    or anno.get("原文")
                    or ""
                ).strip()
                suggestion = str(
                    anno.get("批注内容")
                    or anno.get("comment")
                    or anno.get("修改后文本")
                    or ""
                ).strip()
                reason = str(anno.get("修改原因") or anno.get("reason") or "").strip()
                if original:
                    comment_items.append(
                        {
                            "original": original,
                            "suggestion": suggestion,
                            "reason": reason,
                        }
                    )

            if not comment_items:
                return {
                    "success": False,
                    "applied": 0,
                    "failed": len(annotations or []),
                    "error": "没有可写入的批注",
                }

            comments_el, comments_part_ref = self._get_or_create_comments_part(doc)
            succeeded = 0
            failed = 0
            for item in comment_items:
                ok = self._apply_single_comment(
                    doc,
                    comments_el,
                    item["original"],
                    item["suggestion"],
                    item["reason"],
                )
                if ok:
                    succeeded += 1
                else:
                    failed += 1

            doc.save(file_path)
            if succeeded > 0 and comments_el is not None:
                self._inject_comments_to_docx(file_path, comments_el)

            return {
                "success": True,
                "applied": succeeded,
                "failed": failed,
                "total": len(comment_items),
            }
        except Exception as exc:
            logger.error("[TrackChanges] comment application failed: %s", exc)
            return {
                "success": False,
                "applied": 0,
                "failed": len(annotations or []),
                "error": str(exc),
            }

    def apply_hybrid_changes(
        self, file_path: str, annotations: List[Dict[str, str]], progress_callback=None
    ) -> Dict[str, Any]:
        """
        混合应用两种标注方式：
        1. 精确的短文本修改 → Track Changes（修订标记）
        2. 大段落方向建议 → Comments（批注气泡）

        自动判断规则：
        - 原文 <= 30字且有精确替换文本 → Track Changes
        - 原文 > 30字或只有方向建议 → Comment

        Args:
            file_path: Word文档路径
            annotations: 标注列表
            progress_callback: 进度回调

        Returns:
            {"success": True, "tracked": 15, "commented": 8, "failed": 2}
        """
        try:
            doc = Document(file_path)

            # 分类标注
            track_changes_items = []  # 精确修改
            comment_items = []  # 方向建议

            for anno in annotations:
                original = anno.get("原文片段", anno.get("原文", "")).strip()
                modified = anno.get(
                    "修改后文本", anno.get("修改建议", anno.get("改为", ""))
                ).strip()
                reason = anno.get("修改原因", anno.get("原因", "")).strip()

                if not original:
                    continue

                # 判断标注类型
                # 策略调整：只要提供了具体修改文本且未显式标记为"建议"，均视为修订(Track Changes)
                # 放宽长度限制，允许整句重写
                is_suggestion = (
                    modified.startswith("建议")
                    or modified.startswith("批注")
                    or "建议：" in modified
                    or "原因：" in modified  # 某些情况下AI可能会把原因混入
                )

                is_precise = (
                    modified  # 有替换文本
                    and modified != original  # 不是重复
                    and not is_suggestion  # 不是建议
                    and len(original) < 500  # 长度安全限制，防止整页替换
                )

                if is_precise:
                    # 精确修改 → Track Changes
                    track_changes_items.append(
                        {"original": original, "modified": modified, "reason": reason}
                    )
                else:
                    # 方向建议 → Comment
                    comment_items.append(
                        {"original": original, "modified": modified, "reason": reason}
                    )

            total_items = len(track_changes_items) + len(comment_items)

            logger.info(f"\n[Hybrid] 🎯 混合标注模式")
            logger.info(
                f"[Hybrid] ✏️  精确修改: {len(track_changes_items)} 条（Track Changes）"
            )
            logger.info(f"[Hybrid] 💬 方向建议: {len(comment_items)} 条（Comments）")

            # 先应用 Track Changes
            tracked_success = 0
            tracked_failed = 0
            commented_success = 0
            commented_failed = 0

            if track_changes_items:
                logger.info(f"\n[Hybrid] 📝 第1步：应用精确修改...")

                for idx, item in enumerate(track_changes_items, 1):
                    if progress_callback:
                        progress_callback(
                            idx,
                            len(track_changes_items) + len(comment_items),
                            "tracking",
                            f"修订标记: {item['original'][:20]}...",
                        )

                    success = self._apply_single_track_change(
                        doc, item["original"], item["modified"], item["reason"]
                    )

                    if success:
                        tracked_success += 1
                        doc.save(file_path)
                        if progress_callback:
                            progress_callback(
                                idx,
                                total_items,
                                "saved",
                                f"已写回原文 {tracked_success + commented_success}/{total_items}：{item['original'][:20]}...",
                                file_updated=True,
                                applied=tracked_success + commented_success,
                                file_path=file_path,
                                updated_in_place=True,
                            )
                    else:
                        tracked_failed += 1
                        logger.warning(
                            f"[Hybrid] ⚠️  修订失败: {item['original'][:30]}..."
                        )

            # 再应用 Comments
            comments_el = None
            comments_part_ref = None

            if comment_items:
                logger.info(f"\n[Hybrid] 💬 第2步：添加批注建议...")

                # 获取 comments part
                comments_el, comments_part_ref = self._get_or_create_comments_part(doc)

                for idx, item in enumerate(comment_items, 1):
                    if progress_callback:
                        progress_callback(
                            len(track_changes_items) + idx,
                            len(track_changes_items) + len(comment_items),
                            "commenting",
                            f"批注建议: {item['original'][:20]}...",
                        )

                    success = self._apply_single_comment(
                        doc,
                        comments_el,
                        item["original"],
                        item["modified"],
                        item["reason"],
                    )

                    if success:
                        commented_success += 1
                        comments_part_ref = self._sync_comments_part(
                            doc, comments_el, comments_part_ref
                        )
                        doc.save(file_path)
                        if progress_callback:
                            progress_callback(
                                len(track_changes_items) + idx,
                                total_items,
                                "saved",
                                f"已写回原文 {tracked_success + commented_success}/{total_items}：{item['original'][:20]}...",
                                file_updated=True,
                                applied=tracked_success + commented_success,
                                file_path=file_path,
                                updated_in_place=True,
                            )
                    else:
                        commented_failed += 1
                        logger.warning(
                            f"[Hybrid] ⚠️  批注失败: {item['original'][:30]}..."
                        )

            # 将 comments XML 写入文档 Part（python-docx OPC 方式）
            if commented_success > 0 and comments_el is not None:
                comments_part_ref = self._sync_comments_part(
                    doc, comments_el, comments_part_ref
                )

            # 保存文档
            doc.save(file_path)

            total_success = tracked_success + commented_success
            total_failed = tracked_failed + commented_failed

            logger.info(f"\n[Hybrid] ✅ 完成！")
            logger.info(
                f"[Hybrid] 📊 修订标记: {tracked_success}成功 / {tracked_failed}失败"
            )
            logger.info(
                f"[Hybrid] 📊 批注建议: {commented_success}成功 / {commented_failed}失败"
            )
            logger.info(f"[Hybrid] 📊 总计: {total_success}成功 / {total_failed}失败\n")

            return {
                "success": True,
                "tracked": tracked_success,
                "commented": commented_success,
                "failed": total_failed,
                "total": len(annotations),
                "applied": total_success,
            }

        except Exception as e:
            logger.error(f"[Hybrid] ❌ 混合标注失败: {e}")
            import traceback

            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "tracked": 0,
                "commented": 0,
                "failed": len(annotations),
                "total": len(annotations),
                "applied": 0,
            }

    def _apply_single_track_change(
        self, doc: Document, original_text: str, modified_text: str, reason: str = ""
    ) -> bool:
        """Apply a single Track-Changes revision (del + ins) preserving run formatting."""
        try:
            from copy import deepcopy

            # Build paragraph list: body paragraphs + all table cell paragraphs
            all_paragraphs = list(doc.paragraphs)
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        all_paragraphs.extend(cell.paragraphs)

            # Multi-level normalized search
            found_para, effective_original = _find_para_with_text(
                all_paragraphs, original_text
            )
            if not found_para:
                return False

            para = found_para
            # Strip markdown from modified_text so Track Change text looks clean in Word
            effective_modified = (
                _normalize_text_for_match(modified_text) or modified_text
            )

            # Map runs to character positions
            run_map = []
            current_pos = 0
            full_text_parts = []
            for i, run in enumerate(para.runs):
                text = run.text
                run_map.append(
                    {
                        "start": current_pos,
                        "end": current_pos + len(text),
                        "run": run,
                        "index": i,
                    }
                )
                full_text_parts.append(text)
                current_pos += len(text)

            full_text = "".join(full_text_parts)
            start_idx = full_text.find(effective_original)
            if start_idx == -1:
                return False
            end_idx = start_idx + len(effective_original)

            # Find runs overlapping [start_idx, end_idx]
            target_runs = []
            for info in run_map:
                if max(start_idx, info["start"]) < min(end_idx, info["end"]):
                    target_runs.append(info)

            if not target_runs:
                return False

            runs_to_move = []
            parent = para._element

            s_info = target_runs[0]
            s_run = s_info["run"]
            s_offset = start_idx - s_info["start"]

            e_info = target_runs[-1]
            e_run = e_info["run"]
            e_offset = end_idx - e_info["start"]

            current_time = datetime.now().isoformat()
            self.change_id += 1
            cid = str(self.change_id)

            # ── Case A: change within a single run ───────────────────────────
            if s_info["index"] == e_info["index"]:
                original_run_text = s_run.text
                prefix = original_run_text[:s_offset]
                middle = original_run_text[s_offset:e_offset]
                suffix = original_run_text[e_offset:]

                s_run.text = prefix
                insert_point = s_run._element

                middle_run_elem = deepcopy(s_run._element)
                t = middle_run_elem.find(qn("w:t"))
                if t is None:
                    t = etree.SubElement(middle_run_elem, qn("w:t"))
                t.text = middle

                if suffix:
                    suffix_run_elem = deepcopy(s_run._element)
                    t2 = suffix_run_elem.find(qn("w:t"))
                    if t2 is None:
                        t2 = etree.SubElement(suffix_run_elem, qn("w:t"))
                    t2.text = suffix
                    parent.insert(parent.index(insert_point) + 1, suffix_run_elem)

                runs_to_move.append(middle_run_elem)

            # ── Case B: change spans multiple runs ───────────────────────────
            else:
                s_text = s_run.text
                s_run.text = s_text[:s_offset]
                insert_point = s_run._element

                s_del_elem = deepcopy(s_run._element)
                t = s_del_elem.find(qn("w:t"))
                if t is None:
                    t = etree.SubElement(s_del_elem, qn("w:t"))
                t.text = s_text[s_offset:]
                runs_to_move.append(s_del_elem)

                for info in target_runs[1:-1]:
                    r_elem = info["run"]._element
                    parent.remove(r_elem)
                    runs_to_move.append(r_elem)

                e_text = e_run.text
                e_del_elem = deepcopy(e_run._element)
                t = e_del_elem.find(qn("w:t"))
                if t is None:
                    t = etree.SubElement(e_del_elem, qn("w:t"))
                t.text = e_text[:e_offset]
                runs_to_move.append(e_del_elem)

                e_run.text = e_text[e_offset:]

            # ── Build <w:del> and <w:ins> ─────────────────────────────────────
            base_idx = parent.index(insert_point)

            del_el = parse_xml(
                f'<w:del w:id="{cid}" w:author="{self.author}" w:date="{current_time}"'
                f' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
            )
            for r in runs_to_move:
                for t_el in r.findall(qn("w:t")):
                    t_el.tag = qn("w:delText")
                del_el.append(r)
            parent.insert(base_idx + 1, del_el)

            self.change_id += 1
            ins_el = parse_xml(
                f'<w:ins w:id="{str(self.change_id)}" w:author="{self.author}"'
                f' w:date="{current_time}"'
                f' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f'<w:r><w:t xml:space="preserve">{self._esc(effective_modified)}</w:t></w:r>'
                f"</w:ins>"
            )
            parent.insert(base_idx + 2, ins_el)

            return True

        except Exception as e:
            logger.error(f"[TrackChange] Error: {e}")
            import traceback

            traceback.print_exc()
            return False

    def _inject_comments_to_docx(self, file_path: str, comments_el) -> bool:
        """
        Inject comments_el into the docx zip package after doc.save():
        1. word/comments.xml ? comment content (merging previously written ones)
        2. [Content_Types].xml ? comments content type override
        3. word/_rels/document.xml.rels ? comments relationship
        """
        try:
            tmp_path = file_path + ".tmp"
            existing_comments = []

            with zipfile.ZipFile(file_path, "r") as zin:
                with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
                    for item in zin.infolist():
                        if item.filename == "word/comments.xml":
                            existing_comments = self._existing_comment_elements(
                                zin.read(item.filename)
                            )
                            continue
                        data = zin.read(item.filename)
                        if item.filename == "[Content_Types].xml":
                            data = self._add_comments_content_type(data)
                        elif item.filename == "word/_rels/document.xml.rels":
                            data = self._add_comments_relationship(data)
                        zout.writestr(item, data)

                    existing_ids = {
                        node.get("{%s}id" % _COMMENTS_W_NS)
                        for node in comments_el.findall("{%s}comment" % _COMMENTS_W_NS)
                        if node.get("{%s}id" % _COMMENTS_W_NS)
                    }
                    for existing in existing_comments:
                        if existing.get("{%s}id" % _COMMENTS_W_NS) not in existing_ids:
                            comments_el.append(existing)

                    comments_xml = etree.tostring(
                        comments_el,
                        xml_declaration=True,
                        encoding="UTF-8",
                        standalone=True,
                    )
                    zout.writestr("word/comments.xml", comments_xml)

            shutil.move(tmp_path, file_path)
            logger.info(f"[Hybrid] comments.xml injected ({len(comments_xml)} bytes)")
            return True

        except Exception as exc:
            logger.error("[Hybrid] inject comments.xml failed: %s", exc)
            tmp_path = file_path + ".tmp"
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return False

    @staticmethod
    def _existing_comment_elements(comments_xml: bytes) -> list:
        """Parse previously written word/comments.xml into comment elements."""
        try:
            root = etree.fromstring(comments_xml)
            return list(root.findall("{%s}comment" % _COMMENTS_W_NS))
        except Exception:
            return []

    def _add_comments_content_type(self, content_types_data: bytes) -> bytes:
        """在 [Content_Types].xml 中添加 comments 的 Override"""
        try:
            root = etree.fromstring(content_types_data)
            ns = "http://schemas.openxmlformats.org/package/2006/content-types"

            for override in root.findall(f"{{{ns}}}Override"):
                if override.get("PartName") == "/word/comments.xml":
                    return content_types_data

            override = etree.SubElement(root, f"{{{ns}}}Override")
            override.set("PartName", "/word/comments.xml")
            override.set(
                "ContentType",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
            )

            return etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
        except Exception as e:
            logger.warning(f"[Hybrid] ⚠️ Content_Types 修改失败: {e}")
            return content_types_data

    def _add_comments_relationship(self, rels_data: bytes) -> bytes:
        """在 document.xml.rels 中添加 comments 关系"""
        try:
            root = etree.fromstring(rels_data)
            ns = "http://schemas.openxmlformats.org/package/2006/relationships"

            for rel in root.findall(f"{{{ns}}}Relationship"):
                if "comments" in rel.get("Type", "").lower():
                    return rels_data

            existing_ids = [
                rel.get("Id", "") for rel in root.findall(f"{{{ns}}}Relationship")
            ]
            max_id = 0
            for rid in existing_ids:
                if rid.startswith("rId"):
                    try:
                        max_id = max(max_id, int(rid[3:]))
                    except ValueError:
                        pass
            new_id = f"rId{max_id + 1}"

            rel = etree.SubElement(root, f"{{{ns}}}Relationship")
            rel.set("Id", new_id)
            rel.set(
                "Type",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments",
            )
            rel.set("Target", "comments.xml")

            return etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
        except Exception as e:
            logger.warning(f"[Hybrid] ⚠️ Rels 修改失败: {e}")
            return rels_data

    def _apply_single_comment(
        self,
        doc: Document,
        comments_el,
        original_text: str,
        suggestion_text: str,
        reason: str = "",
        anchor_meta: dict[str, Any] | None = None,
    ) -> bool:
        """应用单个批注（内部方法）"""
        try:
            # Strip Markdown formatting from original_text (same as track-change path)
            stripped = _strip_md_formatting(original_text)
            effective_original = (
                stripped if (stripped and stripped != original_text) else original_text
            )
            anchor_range = self._resolve_comment_anchor_range(
                doc,
                effective_original,
                anchor_meta=anchor_meta,
            )
            if not anchor_range:
                return False

            self.change_id += 1
            comment_id = str(self.change_id)

            comment_content = suggestion_text
            if reason:
                comment_content = f"{suggestion_text}\n\n原因：{reason}"

            comment_xml = f"""
                    <w:comment w:id="{comment_id}" w:author="{self.author}" w:date="{datetime.now().isoformat()}" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                        <w:p>
                            <w:pPr>
                                <w:pStyle w:val="CommentText"/>
                            </w:pPr>
                            <w:r>
                                <w:t>{self._esc(comment_content)}</w:t>
                            </w:r>
                        </w:p>
                    </w:comment>
                    """
            comments_el.append(parse_xml(comment_xml))

            return self._insert_comment_range_markers(
                anchor_range["start_para"],
                int(anchor_range["start_offset"]),
                anchor_range["end_para"],
                int(anchor_range["end_offset"]),
                comment_id,
            )

        except Exception as e:
            logger.info(f"[Comment] 单条批注失败: {e}")
            return False


if __name__ == "__main__":
    logger.info("Track Changes Editor 已准备就绪")
