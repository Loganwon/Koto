# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List


def _parse_json_list(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _project_root() -> str:
    return str(Path(__file__).resolve().parent.parent.parent.parent)


def _workspace_root() -> str:
    return os.path.join(_project_root(), "workspace")


def _safe_resolve_for_compare(path: str) -> str:
    root = _workspace_root()
    project_root = _project_root()
    stripped = path.replace("\\", "/")
    if stripped.startswith("workspace/"):
        stripped = stripped[len("workspace/") :]
    workspace_candidate = os.path.normpath(os.path.join(root, stripped))
    project_candidate = os.path.normpath(os.path.join(project_root, stripped))
    normalized_root = os.path.normpath(root)
    normalized_project = os.path.normpath(project_root)
    if workspace_candidate.startswith(normalized_root) and os.path.exists(
        workspace_candidate
    ):
        return workspace_candidate
    if project_candidate.startswith(normalized_project):
        return project_candidate
    return workspace_candidate


def _normalize_compare_path(path: Any) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    if not os.path.isabs(text):
        cwd_resolved = str(Path(text).resolve())
        compare_resolved = _safe_resolve_for_compare(text)
        if compare_resolved and os.path.exists(compare_resolved):
            text = compare_resolved
        elif os.path.exists(cwd_resolved):
            text = cwd_resolved
        else:
            text = compare_resolved or cwd_resolved
    try:
        return os.path.normcase(os.path.normpath(text))
    except Exception:
        return text.lower()


def _is_bare_filename(path: Any) -> bool:
    text = str(path or "").strip().replace("\\", "/")
    if not text:
        return False
    return "/" not in text and os.path.basename(text) == text


def _path_matches_expected_target(path: Any, expected_target: str) -> bool:
    expected = str(expected_target or "").strip()
    if not expected:
        return False
    normalized_expected = _normalize_compare_path(expected)
    normalized_path = _normalize_compare_path(path)
    if normalized_path and normalized_path == normalized_expected:
        return True
    if not _is_bare_filename(expected):
        return False
    expected_basename = os.path.basename(expected).lower()
    actual_basename = os.path.basename(str(path or "")).lower()
    return bool(expected_basename and actual_basename == expected_basename)


def _verification_summary_from_changes(
    changes: List[Dict[str, Any]], target_path: str = ""
) -> str:
    primary = changes[0] if changes else {}
    primary_path = str(primary.get("path") or target_path or "").strip()
    file_name = os.path.basename(primary_path) or primary_path or "目标文件"
    details: List[str] = []
    operation = str(primary.get("operation") or "").strip()
    fallback_copy = bool(primary.get("fallback_copy"))
    original_target_path = str(
        primary.get("original_target_path") or target_path or ""
    ).strip()
    original_target_name = (
        os.path.basename(original_target_path) or original_target_path
    )

    if operation == "insert_excel_as_docx_table":
        sheet = str(primary.get("sheet") or "").strip()
        rows = int(primary.get("rows_written") or 0)
        cols = int(primary.get("columns_written") or 0)
        if sheet:
            details.append(f"已写入工作表“{sheet}”")
        if rows and cols:
            details.append(f"{rows} 行 × {cols} 列")
        elif rows:
            details.append(f"已写入 {rows} 行")
        if fallback_copy and original_target_name:
            details.append(
                f"原目标文件 {original_target_name} 当前不可写，已输出更新副本"
            )
    elif operation == "design_pptx_theme_layout":
        slides = int(primary.get("slides_designed") or primary.get("total_slides") or 0)
        theme_name = str(primary.get("theme_name") or "").strip()
        if slides:
            details.append(f"已应用 {slides} 页统一主题版式")
        if theme_name:
            details.append(f"主题：{theme_name}")
    elif operation == "write_pptx_slides":
        updated = int(primary.get("slides_updated") or 0)
        if updated:
            details.append(f"已更新 {updated} 页幻灯片")
    elif operation == "add_pptx_slides":
        added = int(primary.get("slides_added") or 0)
        if added:
            details.append(f"已新增 {added} 页幻灯片")
    elif operation == "write_sheet_data":
        cells = int(primary.get("cells_written") or 0)
        if cells:
            details.append(f"已写入 {cells} 个单元格")
    elif operation == "replace_file_selection":
        replacements = int(primary.get("replacements_made") or 0)
        if replacements:
            details.append(f"已替换 {replacements} 处选区")
    elif operation == "write_docx_content":
        paragraphs = int(primary.get("paragraphs_written") or 0)
        if paragraphs:
            details.append(f"已写入 {paragraphs} 个段落")
    elif operation == "insert_image_into_docx":
        images_inserted = int(primary.get("images_inserted") or 0)
        image_name = str(primary.get("image_name") or "").strip()
        caption = str(primary.get("caption") or "").strip()
        if images_inserted:
            details.append(f"已插入 {images_inserted} 张图片")
        if image_name:
            details.append(f"图片：{image_name}")
        if caption:
            details.append(f"说明：{caption}")
    elif operation == "annotate_file":
        annotations = int(primary.get("annotations_added") or 0)
        if annotations:
            details.append(f"已添加 {annotations} 条批注")
    elif operation in {"compare_docx_and_annotate", "write_docx_comments"}:
        differences = int(primary.get("differences_detected") or 0)
        annotations = int(primary.get("annotations_added") or 0)
        if differences:
            details.append(f"已发现 {differences} 处差异")
        if annotations:
            details.append(f"已标注 {annotations} 条差异批注")
    elif operation == "clear_docx_review_marks":
        comments_removed = int(primary.get("comments_removed") or 0)
        revisions_accepted = int(primary.get("revisions_accepted") or 0)
        if comments_removed:
            details.append(f"已清除 {comments_removed} 条批注")
        if revisions_accepted:
            details.append(f"已接受 {revisions_accepted} 处修订")

    warning = str(primary.get("warning") or "").strip()
    if warning:
        details.append(f"提示：{warning}")

    if len(changes) > 1:
        details.append(f"另有 {len(changes) - 1} 个相关文件变更")

    summary = (
        f"已生成更新副本：{file_name}"
        if fallback_copy
        else f"文件已成功修改：{file_name}"
    )
    if details:
        summary += "；" + "，".join(details)
    return summary


def _task_requires_docx_summary_with_excel_table(
    task_description: str, changes: List[Dict[str, Any]], target_path: str = ""
) -> bool:
    text = str(task_description or "").strip().lower()
    if not text:
        return False
    summary_markers = (
        "整理",
        "总结",
        "概括",
        "提炼",
        "分析",
        "说明",
        "结论",
        "要点",
        "摘要",
        "summary",
        "summarize",
        "analysis",
        "analyze",
        "insight",
        "brief",
    )
    if not any(marker in text for marker in summary_markers):
        return False
    target_candidates = [str(target_path or "").strip()]
    target_candidates.extend(
        str(change.get("path") or "").strip()
        for change in changes
        if isinstance(change, dict)
    )
    if not any(
        candidate.lower().endswith(".docx")
        for candidate in target_candidates
        if candidate
    ):
        return False
    return any(
        isinstance(change, dict)
        and str(change.get("operation") or "").strip() == "insert_excel_as_docx_table"
        for change in changes
    )


def _has_docx_narrative_write(
    changes: List[Dict[str, Any]], target_path: str = ""
) -> bool:
    normalized_target = _normalize_compare_path(target_path)
    for change in changes:
        if not isinstance(change, dict):
            continue
        operation = str(change.get("operation") or "").strip()
        if operation != "write_docx_content":
            continue
        if normalized_target:
            if _normalize_compare_path(change.get("path")) != normalized_target:
                continue
        return True
    return False


def verify_task_completion(
    task_description: str,
    file_states: str = "[]",
    model_mode: str = "auto",
    file_changes: str = "[]",
    target_path: str = "",
) -> str:
    """Verify whether a file task has produced the expected persisted output."""
    del model_mode
    states = _parse_json_list(file_states)
    changes = _parse_json_list(file_changes)

    if not states and changes:
        states = [
            {
                "path": change.get("path"),
                "exists": True,
                "modified": True,
                "preview": change.get("preview") or change.get("summary") or "",
            }
            for change in changes
            if str(change.get("path") or "").strip()
        ]

    if not states:
        return json.dumps(
            {
                "completed": False,
                "summary": "无文件状态信息",
                "criteria_results": [
                    {
                        "criterion": "file_state_available",
                        "passed": False,
                        "detail": "无文件状态信息",
                        "priority": "critical",
                    }
                ],
            },
            ensure_ascii=False,
        )

    expected_target = str(target_path or "").strip()
    normalized_target = _normalize_compare_path(expected_target)
    relevant_states = states
    if normalized_target:
        matching_states = [
            state
            for state in states
            if _path_matches_expected_target(state.get("path"), expected_target)
        ]
        matching_changes = [
            change
            for change in changes
            if _path_matches_expected_target(change.get("path"), expected_target)
        ]
        fallback_changes = [
            change
            for change in changes
            if bool(change.get("fallback_copy"))
            and _normalize_compare_path(change.get("original_target_path"))
            == normalized_target
        ]
        if not matching_changes and fallback_changes:
            primary_fallback = fallback_changes[0]
            expected_name = os.path.basename(expected_target) or expected_target
            fallback_name = (
                os.path.basename(str(primary_fallback.get("path") or "")) or "恢复副本"
            )
            blocked_reason = str(primary_fallback.get("blocked_reason") or "").strip()
            summary = f"目标文件尚未完成修改：{expected_name}；已生成恢复副本 {fallback_name}。"
            if blocked_reason:
                summary += blocked_reason
            return json.dumps(
                {
                    "completed": False,
                    "confidence": 0.4,
                    "summary": summary,
                    "remaining_steps": [
                        f"检查 {expected_name} 的文件权限；如果文件正在被占用，关闭相关程序后重新写回原文件"
                    ],
                    "criteria_results": [
                        {
                            "criterion": "target_file_hit",
                            "passed": False,
                            "detail": f"目标文件 {expected_name} 尚未写回原文件，只生成了恢复副本 {fallback_name}。",
                            "priority": "critical",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        if not matching_states and not matching_changes:
            modified_names = [
                os.path.basename(str(state.get("path") or ""))
                for state in states
                if state.get("modified")
            ]
            expected_name = os.path.basename(expected_target) or expected_target
            actual_text = (
                "、".join(name for name in modified_names if name) or "其他文件"
            )
            return json.dumps(
                {
                    "completed": False,
                    "confidence": 0.35,
                    "summary": f"已修改 {actual_text}，但未命中目标文件：{expected_name}",
                    "remaining_steps": [f"把结果写入 {expected_name}"],
                    "criteria_results": [
                        {
                            "criterion": "target_file_hit",
                            "passed": False,
                            "detail": f"已修改 {actual_text}，但未命中目标文件：{expected_name}",
                            "priority": "critical",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        if (
            matching_states
            and not matching_changes
            and not all(state.get("modified") for state in matching_states)
        ):
            expected_name = os.path.basename(expected_target) or expected_target
            return json.dumps(
                {
                    "completed": False,
                    "confidence": 0.5,
                    "summary": f"目标文件尚未完成修改：{expected_name}",
                    "remaining_steps": [f"继续写入 {expected_name}"],
                    "criteria_results": [
                        {
                            "criterion": "target_file_modified",
                            "passed": False,
                            "detail": f"目标文件尚未完成修改：{expected_name}",
                            "priority": "critical",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        if matching_changes:
            changes = matching_changes
            relevant_states = [
                state
                for state in matching_states
                if isinstance(state, dict) and state.get("modified")
            ] or [
                {
                    "path": expected_target
                    or str(matching_changes[0].get("path") or ""),
                    "exists": True,
                    "modified": True,
                    "preview": str(
                        matching_changes[0].get("preview")
                        or matching_changes[0].get("summary")
                        or ""
                    ),
                }
            ]
        else:
            relevant_states = matching_states or [
                {
                    "path": expected_target,
                    "exists": True,
                    "modified": True,
                    "preview": "",
                }
            ]

    all_modified = all(
        state.get("modified") for state in relevant_states if isinstance(state, dict)
    )
    if not all_modified:
        unmodified = [
            os.path.basename(str(state.get("path") or ""))
            for state in relevant_states
            if isinstance(state, dict) and not state.get("modified")
        ]
        return json.dumps(
            {
                "completed": False,
                "confidence": 0.5,
                "summary": f"以下文件尚未修改：{', '.join(unmodified)}",
                "remaining_steps": [f"写入 {name}" for name in unmodified],
                "criteria_results": [
                    {
                        "criterion": "file_state_available",
                        "passed": True,
                        "detail": "已收到文件状态信息。",
                        "priority": "info",
                    },
                    {
                        "criterion": "all_tracked_files_modified",
                        "passed": False,
                        "detail": f"以下文件尚未修改：{', '.join(unmodified)}",
                        "priority": "critical",
                    },
                ],
            },
            ensure_ascii=False,
        )

    if _task_requires_docx_summary_with_excel_table(
        task_description, changes, expected_target
    ) and not _has_docx_narrative_write(changes, expected_target):
        expected_docx = (
            os.path.basename(expected_target)
            or os.path.basename(str((changes[0] if changes else {}).get("path") or ""))
            or "目标 DOCX"
        )
        return json.dumps(
            {
                "completed": False,
                "confidence": 0.45,
                "summary": f"{expected_docx} 已插入表格，但任务还要求整理后的文字内容，当前只写入了表格。",
                "remaining_steps": [
                    "先提炼关键结论，再用 write_docx_content 把摘要/说明写入目标 DOCX"
                ],
                "criteria_results": [
                    {
                        "criterion": "docx_table_inserted",
                        "passed": True,
                        "detail": f"{expected_docx} 已成功插入表格。",
                        "priority": "info",
                    },
                    {
                        "criterion": "docx_narrative_write_present",
                        "passed": False,
                        "detail": f"{expected_docx} 缺少整理后的文字内容，当前只写入了表格。",
                        "priority": "critical",
                    },
                ],
            },
            ensure_ascii=False,
        )

    summary = _verification_summary_from_changes(changes, expected_target)
    return json.dumps(
        {
            "completed": True,
            "confidence": 1.0,
            "summary": summary,
            "remaining_steps": [],
            "criteria_results": [
                {
                    "criterion": "all_tracked_files_modified",
                    "passed": True,
                    "detail": "所有跟踪文件都已完成修改。",
                    "priority": "info",
                },
                (
                    {
                        "criterion": "target_file_hit",
                        "passed": True,
                        "detail": os.path.basename(expected_target) or "已命中目标文件",
                        "priority": "info",
                    }
                    if expected_target
                    else {
                        "criterion": "structured_file_change_present",
                        "passed": True,
                        "detail": "已记录结构化文件变更。",
                        "priority": "info",
                    }
                ),
            ],
        },
        ensure_ascii=False,
    )
