"""Domain module - DOCX annotation tools."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from app.core.agent.toolkits.foundation.docx_compare import (
    _contract_risk_summary_from_annotations,
    _docx_compare_annotation_candidates,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    DOCX_COMMENT_MARKUP_TAGS as _DOCX_COMMENT_MARKUP_TAGS,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    DOCX_W_NS as _DOCX_W_NS,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import _serialize_xml_root
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    accept_docx_revision_markup as _accept_docx_revision_markup,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    build_docx_review_clear_summary as _build_docx_review_clear_summary,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    normalize_docx_review_clear_scope as _review_normalize_docx_review_clear_scope,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    remove_comments_content_type_override as _remove_comments_content_type_override,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    remove_comments_relationships_xml as _remove_comments_relationships_xml,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    remove_docx_comment_markup as _remove_docx_comment_markup,
)

from ..task_tools_common import _DOCX_REVIEW_CLEAR_SCOPE_ALIASES
from ._internal_backup import (
    _best_effort_backup,
    _ensure_existing_file_writable,
    _nonwritable_target_message,
    _nonwritable_target_next_step,
)
from ._internal_formats import _next_available_docx_copy_path
from ._internal_fs import _resolve_path, _result_path
from ._internal_normalize import _normalize_positive_int
from ._internal_results import _blocked_write_result, _success_result
from ._internal_tempfile import _write_bytes_via_temp_file
from ._internal_warnings import _merge_warnings


def plan_docx_compare_annotations(
    original_path: str,
    revised_path: str,
    target_path: str = "",
    max_differences: int = 80,
) -> str:
    """Return DOCX difference anchors so the model can write comment text.

    This tool does not modify files. It finds target-document anchors and
    provides default "另一份为/本文件为" comments that the model may refine before
    calling write_docx_comments.
    """
    original_resolved = _resolve_path(original_path)
    revised_resolved = _resolve_path(revised_path)
    if not original_resolved:
        return json.dumps(
            {"error": f"原始文件不存在: {original_path}"}, ensure_ascii=False
        )
    if not revised_resolved:
        return json.dumps(
            {"error": f"对比文件不存在: {revised_path}"}, ensure_ascii=False
        )
    if Path(original_resolved).suffix.lstrip(".").lower() != "docx":
        return json.dumps(
            {"error": f"只支持 DOCX 原始文件: {original_path}"}, ensure_ascii=False
        )
    if Path(revised_resolved).suffix.lstrip(".").lower() != "docx":
        return json.dumps(
            {"error": f"只支持 DOCX 对比文件: {revised_path}"}, ensure_ascii=False
        )

    target_raw = str(target_path or original_path or "").strip()
    target_resolved = _resolve_path(target_raw) if target_raw else original_resolved
    if not target_resolved:
        return json.dumps(
            {"error": f"目标 DOCX 不存在: {target_raw}"}, ensure_ascii=False
        )
    if Path(target_resolved).suffix.lstrip(".").lower() != "docx":
        return json.dumps(
            {"error": f"目标文件必须是 DOCX: {target_raw}"}, ensure_ascii=False
        )

    try:
        max_items = _normalize_positive_int(max_differences, default=80, upper=200)
        annotations, differences_detected = _docx_compare_annotation_candidates(
            original_resolved,
            revised_resolved,
            target_resolved,
            max_differences=max_items,
        )
        risks = _contract_risk_summary_from_annotations(annotations)
        return json.dumps(
            {
                "success": True,
                "operation": "plan_docx_compare_annotations",
                "original_path": _result_path(original_path, original_resolved),
                "revised_path": _result_path(revised_path, revised_resolved),
                "target_path": _result_path(target_raw, target_resolved),
                "differences_detected": differences_detected,
                "annotation_candidates": annotations,
                "contract_risk_summary": risks,
                "summary": f"已定位 {len(annotations)} 处可写入目标 DOCX 的差异批注候选。",
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def write_docx_comments(
    path: str,
    comments_json: Any = "[]",
    source_path: str = "",
    compare_path: str = "",
    differences_detected: int = 0,
) -> str:
    """Write model-authored Word comments into an existing DOCX in place."""
    target_resolved = _resolve_path(path)
    if not target_resolved:
        return json.dumps({"error": f"目标 DOCX 不存在: {path}"}, ensure_ascii=False)
    if Path(target_resolved).suffix.lstrip(".").lower() != "docx":
        return json.dumps({"error": f"目标文件必须是 DOCX: {path}"}, ensure_ascii=False)

    try:
        annotations = _parse_annotations_payload(comments_json)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    normalized: List[Dict[str, str]] = []
    for item in annotations:
        if not isinstance(item, dict):
            continue
        anchor = str(
            item.get("原文片段")
            or item.get("anchor_text")
            or item.get("anchor")
            or item.get("text")
            or item.get("target_text")
            or ""
        ).strip()
        comment = str(
            item.get("批注内容")
            or item.get("comment")
            or item.get("note")
            or item.get("修改后文本")
            or ""
        ).strip()
        if not anchor or not comment:
            continue
        normalized.append(
            {
                "原文片段": anchor,
                "批注内容": comment,
                "批注标签": str(
                    item.get("批注标签") or item.get("label") or ""
                ).strip(),
                "修改原因": str(
                    item.get("修改原因") or item.get("reason") or ""
                ).strip(),
            }
        )

    if not normalized:
        return json.dumps({"error": "没有可写入的 DOCX 批注"}, ensure_ascii=False)

    try:
        from app.core.file.track_changes import TrackChangesEditor
    except ImportError:
        return json.dumps({"error": "缺少 Word 批注写入组件"}, ensure_ascii=False)

    try:
        backup_warning = _best_effort_backup(target_resolved)
        write_warning = _ensure_existing_file_writable(target_resolved)
        editor = TrackChangesEditor(author="Koto AI")
        applied = editor.apply_comment_changes(target_resolved, normalized)
        if not applied.get("success"):
            return json.dumps(
                {"error": str(applied.get("error") or "DOCX 批注写入失败")},
                ensure_ascii=False,
            )
        annotations_added = int(applied.get("applied") or 0)
        failed = int(applied.get("failed") or 0)
        risks = _contract_risk_summary_from_annotations(normalized)
        detected = _normalize_positive_int(
            differences_detected, default=len(normalized), upper=10000
        )
        return _success_result(
            _result_path(path, target_resolved),
            operation="write_docx_comments",
            summary=f"已在目标 DOCX 原文上写入 {annotations_added} 条 Word 批注。",
            file_type="docx",
            change_type="annotate",
            preview="\n".join(
                [
                    f"差异候选：{detected}",
                    f"已写入批注：{annotations_added}",
                    *([f"未能定位：{failed}"] if failed else []),
                ]
            ),
            focus=True,
            annotations_added=annotations_added,
            differences_detected=detected,
            comments_failed=failed,
            source_path=source_path,
            compare_path=compare_path,
            contract_risk_summary=risks,
            warning=_merge_warnings(backup_warning, write_warning),
        )
    except PermissionError as exc:
        return _blocked_write_result(
            _result_path(path, target_resolved),
            summary=str(exc).strip() or _nonwritable_target_message(target_resolved),
            suggested_next_step=_nonwritable_target_next_step(target_resolved),
            operation="write_docx_comments",
            file_type="docx",
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def compare_docx_and_annotate(
    original_path: str,
    revised_path: str,
    target_path: str = "",
    max_differences: int = 80,
) -> str:
    """Compare two DOCX files and mark differences with Word comments.

    The comments are written to target_path when provided, otherwise to revised_path.
    The annotated text always comes from the actual target document; the other
    DOCX is used only as the comparison source.
    """
    original_resolved = _resolve_path(original_path)
    revised_resolved = _resolve_path(revised_path)
    if not original_resolved:
        return json.dumps(
            {"error": f"原始文件不存在: {original_path}"}, ensure_ascii=False
        )
    if not revised_resolved:
        return json.dumps(
            {"error": f"对比文件不存在: {revised_path}"}, ensure_ascii=False
        )
    if Path(original_resolved).suffix.lstrip(".").lower() != "docx":
        return json.dumps(
            {"error": f"只支持 DOCX 原始文件: {original_path}"}, ensure_ascii=False
        )
    if Path(revised_resolved).suffix.lstrip(".").lower() != "docx":
        return json.dumps(
            {"error": f"只支持 DOCX 对比文件: {revised_path}"}, ensure_ascii=False
        )

    target_raw = str(target_path or revised_path or "").strip()
    target_resolved = _resolve_path(target_raw) if target_raw else revised_resolved
    if not target_resolved:
        return json.dumps(
            {"error": f"目标 DOCX 不存在: {target_raw}"}, ensure_ascii=False
        )
    if Path(target_resolved).suffix.lstrip(".").lower() != "docx":
        return json.dumps(
            {"error": f"目标文件必须是 DOCX: {target_raw}"}, ensure_ascii=False
        )

    try:
        from app.core.file.track_changes import TrackChangesEditor
    except ImportError:
        return json.dumps({"error": "缺少 Word 批注写入组件"}, ensure_ascii=False)

    try:
        max_items = _normalize_positive_int(max_differences, default=80, upper=200)
        annotations, differences_detected = _docx_compare_annotation_candidates(
            original_resolved,
            revised_resolved,
            target_resolved,
            max_differences=max_items,
        )
        contract_risk_summary = _contract_risk_summary_from_annotations(annotations)
        if not annotations:
            return _success_result(
                _result_path(target_raw, target_resolved),
                operation="compare_docx_and_annotate",
                summary="两份 DOCX 未发现可标注的正文差异。",
                file_type="docx",
                change_type="annotate",
                preview="未发现正文差异",
                focus=True,
                annotations_added=0,
                differences_detected=0,
                source_path=_result_path(original_path, original_resolved),
                compare_path=_result_path(revised_path, revised_resolved),
            )

        backup_warning = _best_effort_backup(target_resolved)
        write_warning = _ensure_existing_file_writable(target_resolved)
        editor = TrackChangesEditor(author="Koto AI")
        applied = editor.apply_comment_changes(target_resolved, annotations)
        if not applied.get("success"):
            return json.dumps(
                {"error": str(applied.get("error") or "DOCX 差异批注写入失败")},
                ensure_ascii=False,
            )
        annotations_added = int(applied.get("applied") or 0)
        failed = int(applied.get("failed") or 0)
        preview_lines = [
            f"发现差异：{differences_detected}",
            f"已标注批注：{annotations_added}",
        ]
        if failed:
            preview_lines.append(f"未能定位：{failed}")
        if annotations:
            preview_lines.append(
                str(
                    annotations[0].get("批注内容")
                    or annotations[0].get("修改后文本")
                    or ""
                )[:160]
            )
        return _success_result(
            _result_path(target_raw, target_resolved),
            operation="compare_docx_and_annotate",
            summary=f"已对比两份 DOCX，并在目标文档标注 {annotations_added} 处差异。",
            file_type="docx",
            change_type="annotate",
            preview="\n".join(preview_lines),
            focus=True,
            annotations_added=annotations_added,
            differences_detected=differences_detected,
            comments_failed=failed,
            source_path=_result_path(original_path, original_resolved),
            compare_path=_result_path(revised_path, revised_resolved),
            contract_risk_summary=contract_risk_summary,
            warning=_merge_warnings(backup_warning, write_warning),
        )
    except PermissionError as exc:
        return _blocked_write_result(
            _result_path(target_raw, target_resolved),
            summary=str(exc).strip() or _nonwritable_target_message(target_resolved),
            suggested_next_step=_nonwritable_target_next_step(target_resolved),
            operation="compare_docx_and_annotate",
            file_type="docx",
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def _parse_annotations_payload(annotations: Any) -> List[Any]:
    try:
        ann_list = (
            json.loads(annotations) if isinstance(annotations, str) else annotations
        )
    except json.JSONDecodeError as e:
        raise ValueError(f"无效的 annotations JSON: {e}") from e
    if ann_list in (None, ""):
        return []
    if not isinstance(ann_list, list):
        raise ValueError("annotations 必须是 JSON 数组")
    return ann_list


def _normalize_docx_review_clear_scope(scope: str) -> str:
    return _review_normalize_docx_review_clear_scope(
        scope,
        _DOCX_REVIEW_CLEAR_SCOPE_ALIASES,
    )


def clear_docx_review_marks(path: str, scope: str = "comments") -> str:
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
    if Path(resolved).suffix.lstrip(".").lower() != "docx":
        return json.dumps({"error": f"只支持 DOCX 文件: {path}"}, ensure_ascii=False)

    try:
        normalized_scope = _normalize_docx_review_clear_scope(scope)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    try:
        from lxml import etree
    except ImportError:
        return json.dumps({"error": "lxml not installed"}, ensure_ascii=False)

    backup_warning = _best_effort_backup(resolved)
    write_warning = _ensure_existing_file_writable(resolved)

    try:
        with zipfile.ZipFile(resolved, "r") as archive:
            entries = {
                info.filename: archive.read(info.filename)
                for info in archive.infolist()
            }
    except zipfile.BadZipFile as exc:
        return json.dumps({"error": f"无法读取 DOCX 压缩包: {exc}"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    document_xml = entries.get("word/document.xml")
    if not document_xml:
        return json.dumps({"error": "DOCX 缺少 word/document.xml"}, ensure_ascii=False)

    try:
        document_root = etree.fromstring(document_xml)
    except Exception as exc:
        return json.dumps(
            {"error": f"无法解析 DOCX 正文 XML: {exc}"}, ensure_ascii=False
        )

    changed = False
    comments_removed = 0
    comment_markup_removed = 0
    revisions_accepted = 0

    if normalized_scope in {"comments", "all"}:
        comments_xml = entries.pop("word/comments.xml", None)
        if comments_xml is not None:
            try:
                comments_root = etree.fromstring(comments_xml)
                comments_removed = len(
                    comments_root.xpath(".//w:comment", namespaces={"w": _DOCX_W_NS})
                )
            except Exception:
                comments_removed = 0
            changed = True

        comment_markup_removed = _remove_docx_comment_markup(document_root)
        if comment_markup_removed:
            changed = True

        rels_xml = entries.get("word/_rels/document.xml.rels")
        if rels_xml is not None:
            updated_rels, rels_removed = _remove_comments_relationships_xml(rels_xml)
            if rels_removed:
                entries["word/_rels/document.xml.rels"] = updated_rels
                changed = True

        content_types_xml = entries.get("[Content_Types].xml")
        if content_types_xml is not None:
            (
                updated_content_types,
                overrides_removed,
            ) = _remove_comments_content_type_override(content_types_xml)
            if overrides_removed:
                entries["[Content_Types].xml"] = updated_content_types
                changed = True

        approx_comments = comment_markup_removed // len(_DOCX_COMMENT_MARKUP_TAGS)
        if comment_markup_removed and not approx_comments:
            approx_comments = 1
        comments_removed = max(comments_removed, approx_comments)

    if normalized_scope in {"revisions", "all"}:
        revisions_accepted = _accept_docx_revision_markup(document_root)
        if revisions_accepted:
            changed = True

    if changed:
        entries["word/document.xml"] = _serialize_xml_root(document_root)

    summary = _build_docx_review_clear_summary(
        normalized_scope,
        comments_removed,
        revisions_accepted,
        changed=changed,
    )
    preview_lines: List[str] = []
    if normalized_scope in {"comments", "all"}:
        preview_lines.append(f"批注: {comments_removed}")
    if normalized_scope in {"revisions", "all"}:
        preview_lines.append(f"修订: {revisions_accepted}")

    if not changed:
        result_warning = _merge_warnings(backup_warning, write_warning)
        return _success_result(
            _result_path(path, resolved),
            operation="clear_docx_review_marks",
            summary=summary,
            file_type="docx",
            change_type="modify",
            preview="\n".join(preview_lines),
            focus=False,
            changed=False,
            scope=normalized_scope,
            comments_removed=comments_removed,
            comment_markup_removed=comment_markup_removed,
            revisions_accepted=revisions_accepted,
            warning=result_warning,
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    docx_bytes = buffer.getvalue()

    try:
        _write_bytes_via_temp_file(docx_bytes, resolved, suffix=".docx")
    except PermissionError as exc:
        locked_message = str(exc).strip() or _nonwritable_target_message(resolved)
        try:
            fallback_resolved = _next_available_docx_copy_path(resolved)
            _write_bytes_via_temp_file(docx_bytes, fallback_resolved, suffix=".docx")
        except Exception:
            return _blocked_write_result(
                _result_path(path, resolved),
                summary=locked_message,
                suggested_next_step=_nonwritable_target_next_step(resolved),
                scope=normalized_scope,
                comments_removed=comments_removed,
                comment_markup_removed=comment_markup_removed,
                revisions_accepted=revisions_accepted,
            )

        result_warning = _merge_warnings(
            backup_warning,
            write_warning,
            f"原目标文件 {os.path.basename(resolved)} 当前不可写，结果已写入同目录副本 {os.path.basename(fallback_resolved)}。",
        )
        return _blocked_write_result(
            _result_path(fallback_resolved, fallback_resolved),
            summary=(
                f"原目标文件 {os.path.basename(resolved)} 当前不可写，尚未写回原文件；"
                f"已将清理结果写入恢复副本 {os.path.basename(fallback_resolved)}"
            ),
            suggested_next_step=_nonwritable_target_next_step(resolved),
            operation="clear_docx_review_marks",
            file_type="docx",
            change_type="create",
            preview="\n".join(preview_lines),
            focus=True,
            warning=result_warning,
            original_target_path=_result_path(path, resolved),
            blocked_target=True,
            blocked_reason=locked_message,
            fallback_copy=True,
            scope=normalized_scope,
            comments_removed=comments_removed,
            comment_markup_removed=comment_markup_removed,
            revisions_accepted=revisions_accepted,
        )

    result_warning = _merge_warnings(backup_warning, write_warning)
    return _success_result(
        _result_path(path, resolved),
        operation="clear_docx_review_marks",
        summary=summary,
        file_type="docx",
        change_type="modify",
        preview="\n".join(preview_lines),
        focus=True,
        changed=True,
        scope=normalized_scope,
        comments_removed=comments_removed,
        comment_markup_removed=comment_markup_removed,
        revisions_accepted=revisions_accepted,
        warning=result_warning,
    )
