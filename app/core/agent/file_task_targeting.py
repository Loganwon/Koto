# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_runtime_patterns import (
    _OUTPUT_PATH_CONTEXT_PATTERNS,
    _SOURCE_PATH_CONTEXT_PATTERNS,
    _TASK_TEXT_FILE_EXTENSIONS,
    _TASK_TEXT_FILE_REFERENCE_PATTERN,
    _TASK_TEXT_OUTPUT_EXTENSIONS,
)
from app.core.agent.file_task_tool_catalog import is_write_tool, write_target_for_tool
from app.core.agent.file_task_workflow_state import workflow_resume_control

logger = logging.getLogger(__name__)

BoolPredicate = Callable[[str], bool]
PathComparator = Callable[[Any, Any], bool]
PathResolver = Callable[[Any], str]

_TASK_TEXT_DIRECTORY_SEGMENT = (
    r"(?:[A-Za-z]:[\\/])?[^\s\"'<>|,，。；;、!?！？()（）\[\]【】]+"
)
_TASK_TEXT_DIRECTORY_MARKER = (
    r"(?:目录下|目录中|目录里|目录|文件夹下|文件夹中|文件夹里|文件夹|folder|directory)"
)
_TASK_TEXT_OUTPUT_DIRECTORY_VERB = (
    r"(?:保存在|保存到|保存至|输出到|输出至|导出到|写入到|放到|放在|存到|存入|"
    r"save(?:d)?\s+(?:in|to)|export\s+to|write\s+to)"
)
_TASK_TEXT_FILENAME_LABEL = (
    r"(?:文件名为|文件名是|文件命名为|命名为|名为|filename\s*(?:is|:)?|named|called)"
)


def request_with_target_path(
    request: FileTaskRequest,
    target_path: str,
) -> FileTaskRequest:
    clean_target = target_path_with_file_alias(request, target_path)
    if not clean_target:
        return request
    return FileTaskRequest(
        task=request.task,
        run_id=request.run_id,
        session_id=request.session_id,
        files=list(request.files),
        current_file=request.current_file,
        selection=request.selection,
        selection_source=request.selection_source,
        target_path=clean_target,
        model_mode=request.model_mode,
        model_id=request.model_id,
        history=list(request.history),
        options=dict(request.options),
        routing_decision=request.routing_decision,
    )


def target_path_with_file_alias(request: FileTaskRequest, target_path: str) -> str:
    clean_target = str(target_path or "").strip()
    if not clean_target:
        return ""
    if "/" in clean_target.replace("\\", "/").strip("/"):
        return clean_target
    target_name = Path(clean_target.replace("\\", "/")).name.casefold()
    if not target_name:
        return clean_target

    candidates: List[FileTaskFile] = []
    for file_info in [*list(request.files or []), request.current_file]:
        if not file_info:
            continue
        path_text = str(file_info.path or "").strip()
        name_text = str(file_info.name or "").strip() or (
            Path(path_text.replace("\\", "/")).name if path_text else ""
        )
        if name_text.casefold() != target_name:
            continue
        if not path_text or _is_weak_context_path(file_info):
            continue
        candidates.append(file_info)

    if not candidates:
        return clean_target

    target_candidates = [item for item in candidates if item.target] or candidates
    unique_paths = {
        _context_file_key(item): str(item.path or "").strip()
        for item in target_candidates
        if str(item.path or "").strip()
    }
    if len(unique_paths) == 1:
        return next(iter(unique_paths.values()))
    return clean_target


def request_target_points_to_source(
    request: FileTaskRequest,
    target_path: str,
    *,
    same_path: PathComparator,
) -> bool:
    clean_target = str(target_path or "").strip()
    if not clean_target:
        return False
    candidates = [*list(request.files or [])]
    if request.current_file is not None:
        candidates.append(request.current_file)
    for file_info in candidates:
        if not file_info:
            continue
        path_text = str(file_info.path or file_info.name or "").strip()
        if path_text and same_path(clean_target, path_text):
            return True
    return False


def explicit_output_path_from_task(
    task: str,
    *,
    has_artifact_creation_intent: BoolPredicate,
) -> str:
    task_text = str(task or "").strip()
    if not task_text or not has_artifact_creation_intent(task_text):
        return ""
    candidates: List[tuple[int, int, str]] = []
    for match in _TASK_TEXT_FILE_REFERENCE_PATTERN.finditer(task_text):
        raw_path = match.group("path").strip(" \t\r\n,，。；;、!?！？()（）[]【】\"'")
        suffix = Path(raw_path.replace("\\", "/")).suffix.lower().lstrip(".")
        if suffix not in _TASK_TEXT_OUTPUT_EXTENSIONS:
            continue
        start, end = match.span("path")
        before = task_text[max(0, start - 72) : start]
        after = task_text[end : min(len(task_text), end + 48)]
        near = f"{before}{after}"
        if _candidate_path_has_local_write_negation(before):
            continue
        if _candidate_path_is_immediate_source_reference(before, after, suffix):
            continue
        candidate_path = _path_with_split_output_directory(task_text, raw_path, start, end)
        score = 0
        if suffix in {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "pdf"}:
            score += 2
        if any(pattern.search(near) for pattern in _OUTPUT_PATH_CONTEXT_PATTERNS):
            score += 5
        if any(pattern.search(near) for pattern in _SOURCE_PATH_CONTEXT_PATTERNS):
            score -= 3
        if re.search(r"(?:新|新的|目标|输出|结果|产出)", near, re.IGNORECASE):
            score += 2
        if re.search(r"(?:原文件|源文件|输入文件|已添加)", near, re.IGNORECASE):
            score -= 2
        if candidate_path != raw_path:
            score += 8
        if re.search(rf"{_TASK_TEXT_FILENAME_LABEL}\s*$", before, re.IGNORECASE):
            score += 6
        if score > 0:
            candidates.append((score, start, candidate_path))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def explicit_output_paths_from_task(
    task: str,
    *,
    has_artifact_creation_intent: BoolPredicate,
) -> List[str]:
    task_text = str(task or "").strip()
    if not task_text or not has_artifact_creation_intent(task_text):
        return []
    candidates: List[tuple[int, int, str]] = []
    for match in _TASK_TEXT_FILE_REFERENCE_PATTERN.finditer(task_text):
        raw_path = match.group("path").strip(" \t\r\n,，。；;、!?！？()（）[]【】\"'")
        suffix = Path(raw_path.replace("\\", "/")).suffix.lower().lstrip(".")
        if suffix not in _TASK_TEXT_OUTPUT_EXTENSIONS:
            continue
        start, end = match.span("path")
        before = task_text[max(0, start - 72) : start]
        after = task_text[end : min(len(task_text), end + 72)]
        near = f"{before}{after}"
        if _candidate_path_has_local_write_negation(before):
            continue
        if _candidate_path_is_immediate_source_reference(before, after, suffix):
            continue
        candidate_path = _path_with_split_output_directory(task_text, raw_path, start, end)
        score = 0
        if any(pattern.search(near) for pattern in _OUTPUT_PATH_CONTEXT_PATTERNS):
            score += 5
        if any(pattern.search(near) for pattern in _SOURCE_PATH_CONTEXT_PATTERNS):
            score -= 3
        if re.search(r"(?:新|新的|目标|输出|结果|产出)", near, re.IGNORECASE):
            score += 2
        if re.search(r"(?:原文件|源文件|输入文件|已添加)", near, re.IGNORECASE):
            score -= 2
        if candidate_path != raw_path:
            score += 8
        if re.search(rf"{_TASK_TEXT_FILENAME_LABEL}\s*$", before, re.IGNORECASE):
            score += 6
        if score > 0:
            candidates.append((score, start, candidate_path))

    seen: set[str] = set()
    outputs: List[str] = []
    for _score, _start, candidate_path in sorted(candidates, key=lambda item: item[1]):
        normalized = candidate_path.replace("\\", "/").casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        outputs.append(candidate_path)
    return outputs


def explicit_write_target_path_from_task(task: str) -> str:
    task_text = str(task or "").strip()
    if not task_text:
        return ""
    candidates: List[tuple[int, int, str]] = []
    for match in _TASK_TEXT_FILE_REFERENCE_PATTERN.finditer(task_text):
        raw_path = match.group("path").strip(" \t\r\n,，。；;、!?！？()（）[]【】\"'")
        suffix = Path(raw_path.replace("\\", "/")).suffix.lower().lstrip(".")
        if suffix not in _TASK_TEXT_OUTPUT_EXTENSIONS:
            continue
        start, end = match.span("path")
        before = task_text[max(0, start - 80) : start]
        after = task_text[end : min(len(task_text), end + 80)]
        near = f"{before}{after}"
        if _candidate_path_has_local_write_negation(before):
            continue
        if _candidate_path_is_immediate_source_reference(before, after, suffix):
            continue
        if _readonly_attached_source_reference(task_text, near, before):
            continue
        candidate_path = _path_with_split_output_directory(task_text, raw_path, start, end)
        score = 0
        if any(pattern.search(near) for pattern in _OUTPUT_PATH_CONTEXT_PATTERNS):
            score += 5
        if re.search(
            r"(?:继续优化|优化|修改|更新|保存|写入|写回|追加|添加|插入|落盘|"
            r"continue|improve|modify|edit|update|save|write|append|insert)",
            near,
            re.IGNORECASE,
        ):
            score += 5
        if re.search(r"(?:同一个|当前|目标|target|same)", near, re.IGNORECASE):
            score += 2
        if re.search(
            r"(?:同一个|当前|目标).{0,16}(?:docx|word|xlsx|excel|pptx|ppt|pdf|文档|表格|幻灯片|文件)",
            near,
            re.IGNORECASE,
        ):
            score += 5
        if any(pattern.search(near) for pattern in _SOURCE_PATH_CONTEXT_PATTERNS):
            score -= 2
        if re.search(
            r"(?:不要|不用|无需|不需要|不必|别|不|do not|don't|dont|without)"
            r".{0,24}(?:修改|改动|编辑|覆盖|替换|删除|写入|写回|更新|modify|edit|overwrite|replace|delete|write|update)"
            r".{0,36}$",
            before,
            re.IGNORECASE,
        ):
            score -= 8
        if candidate_path != raw_path:
            score += 8
        if re.search(rf"{_TASK_TEXT_FILENAME_LABEL}\s*$", before, re.IGNORECASE):
            score += 6
        if score > 0:
            candidates.append((score, start, candidate_path))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return candidates[0][2]


def _candidate_path_has_local_write_negation(before: str) -> bool:
    local_clause = re.split(r"[。!?！？；;\r\n]", str(before or ""))[-1]
    if not local_clause:
        return False
    return bool(
        re.search(
            r"(?:不要|不用|无需|不需要|不必|别|不).{0,80}"
            r"(?:修改|改动|编辑|覆盖|替换|删除|写入|写回|更新)",
            local_clause,
            re.IGNORECASE,
        )
        or re.search(
            r"(?:do not|don't|dont|no need to|without).{0,80}"
            r"(?:modify|edit|overwrite|replace|delete|write|update)",
            local_clause,
            re.IGNORECASE,
        )
    )


def _candidate_path_is_immediate_source_reference(before: str, after: str, suffix: str) -> bool:
    before_text = str(before or "")
    after_text = str(after or "")
    local_before = re.split(r"[。!?！？；;\r\n]", before_text)[-1]
    if re.search(
        r"(?:读取|阅读|查看|分析|基于|来自|打开|导入|read|source|from|input)(?:的|该|这个|这份|当前)?\s*$",
        local_before,
        re.IGNORECASE,
    ):
        return True
    if suffix in {"xls", "xlsx", "csv"} and re.match(
        r"\s*(?:的|中|里|内|里的|中的|sheet|worksheet).{0,40}"
        r"(?:工作表|sheet|worksheet|数据|表格|rows?|cells?)",
        after_text,
        re.IGNORECASE,
    ):
        return True
    return False


def _path_with_split_output_directory(
    task_text: str,
    raw_path: str,
    start: int,
    end: int,
) -> str:
    clean_path = str(raw_path or "").strip()
    if not clean_path:
        return ""
    normalized_path = clean_path.replace("\\", "/")
    if "/" in normalized_path.strip("/"):
        return clean_path
    before = str(task_text or "")[max(0, start - 140) : start]
    after = str(task_text or "")[end : min(len(str(task_text or "")), end + 140)]
    directory = _split_output_directory_after_file(after) or _split_output_directory_before_file(before)
    if not directory:
        return clean_path
    file_name = Path(normalized_path).name
    clean_dir = directory.replace("\\", "/").rstrip("/")
    if not clean_dir or not file_name:
        return clean_path
    return f"{clean_dir}/{file_name}"


def _split_output_directory_after_file(after: str) -> str:
    match = re.search(
        rf"^[\s,，。；;、]*(?:{_TASK_TEXT_OUTPUT_DIRECTORY_VERB})\s*"
        rf"(?P<directory>{_TASK_TEXT_DIRECTORY_SEGMENT})\s*(?:{_TASK_TEXT_DIRECTORY_MARKER})",
        str(after or ""),
        re.IGNORECASE,
    )
    if not match:
        return ""
    return _clean_split_output_directory(match.group("directory"))


def _split_output_directory_before_file(before: str) -> str:
    match = re.search(
        rf"(?:{_TASK_TEXT_OUTPUT_DIRECTORY_VERB})\s*"
        rf"(?P<directory>{_TASK_TEXT_DIRECTORY_SEGMENT})\s*(?:{_TASK_TEXT_DIRECTORY_MARKER})"
        rf".{{0,80}}(?:{_TASK_TEXT_FILENAME_LABEL})?\s*$",
        str(before or ""),
        re.IGNORECASE,
    )
    if not match:
        return ""
    return _clean_split_output_directory(match.group("directory"))


def _clean_split_output_directory(directory: str) -> str:
    clean = str(directory or "").strip(" \t\r\n,，。；;、!?！？()（）[]【】\"'")
    clean = clean.replace("\\", "/").strip("/")
    if not clean:
        return ""
    suffix = Path(clean).suffix.lower().lstrip(".")
    if suffix in _TASK_TEXT_OUTPUT_EXTENSIONS:
        return ""
    return clean


def _strong_output_reference_file_names(task_text: str) -> set[str]:
    names: set[str] = set()
    source = str(task_text or "")
    if not source:
        return names
    for match in _TASK_TEXT_FILE_REFERENCE_PATTERN.finditer(source):
        raw_path = match.group("path").strip(" \t\r\n,，。；;、!?！？()（）[]【】\"'")
        suffix = Path(raw_path.replace("\\", "/")).suffix.lower().lstrip(".")
        if suffix not in _TASK_TEXT_OUTPUT_EXTENSIONS:
            continue
        start, end = match.span("path")
        before = source[max(0, start - 100) : start]
        after = source[end : min(len(source), end + 120)]
        if _candidate_path_is_immediate_source_reference(before, after, suffix):
            continue
        split_path = _path_with_split_output_directory(source, raw_path, start, end)
        if split_path != raw_path or re.search(
            rf"{_TASK_TEXT_FILENAME_LABEL}\s*$",
            before,
            re.IGNORECASE,
        ):
            name = Path(raw_path.replace("\\", "/")).name.casefold()
            if name:
                names.add(name)
    return names


def _readonly_attached_source_reference(task: str, near: str, before: str) -> bool:
    task_text = str(task or "")
    if not task_text:
        return False
    if any(pattern.search(before) for pattern in _OUTPUT_PATH_CONTEXT_PATTERNS):
        return False
    readonly = (
        re.search(
            r"(?:只读|只分析|只读取|只给答案|只做只读分析)", task_text, re.IGNORECASE
        )
        or re.search(
            r"(?:不要|不用|无需|不需要|不必|别|不).{0,12}"
            r"(?:修改|改动|编辑|写入|写回|更新|保存|插入|删除|替换|应用)",
            task_text,
            re.IGNORECASE,
        )
        or re.search(
            r"(?:read[ -]?only|only analyze|analysis only|answer only|do not|don't|dont|without).{0,24}"
            r"(?:modify|edit|write|update|save|insert|replace|apply)?",
            task_text,
            re.IGNORECASE,
        )
    )
    if not readonly:
        return False
    return bool(
        re.search(
            r"(?:附件|附加|已添加|添加的|分析文档|拖入|上传|attached|uploaded)",
            near,
            re.IGNORECASE,
        )
    )


def same_task_path(
    left: Any,
    right: Any,
    *,
    resolve_task_file_path: PathResolver,
) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    left_norm = left_text.replace("\\", "/").rstrip("/").casefold()
    right_norm = right_text.replace("\\", "/").rstrip("/").casefold()
    if left_norm == right_norm:
        return True
    if Path(left_norm).name and Path(left_norm).name == Path(right_norm).name:
        left_resolved = resolve_task_file_path(left_text)
        right_resolved = resolve_task_file_path(right_text)
        if left_resolved and right_resolved:
            return os.path.normcase(left_resolved) == os.path.normcase(right_resolved)
    return False


def should_skip_uncreated_target_context(
    request: FileTaskRequest,
    file_info: FileTaskFile,
    *,
    same_path: PathComparator,
    has_artifact_creation_intent: BoolPredicate,
    resolve_task_file_path: PathResolver,
) -> bool:
    if not getattr(file_info, "target", False):
        return False
    path_text = str(file_info.path or file_info.name or "").strip()
    if not path_text or not same_path(path_text, request.target_path):
        return False
    if not has_artifact_creation_intent(request.task):
        return False
    return not bool(resolve_task_file_path(path_text))


def context_files(
    request: FileTaskRequest,
    *,
    explicitly_mentioned_files: List[FileTaskFile],
) -> List[FileTaskFile]:
    seen: Dict[str, FileTaskFile] = {}
    result: List[FileTaskFile] = []
    candidates: List[Optional[FileTaskFile]] = []
    resume_control = workflow_resume_control(request)

    def append_path_candidate(path_value: Any, *, target: bool = False) -> None:
        path_text = str(path_value or "").strip()
        if not path_text:
            return
        suffix = Path(path_text).suffix.lower().lstrip(".")
        if not suffix:
            return
        candidates.append(
            FileTaskFile(
                path=path_text,
                name=Path(path_text).name,
                type=suffix,
                target=target,
            )
        )

    if str(resume_control.get("policy") or "").strip().lower() == "confirm_each_step":
        append_path_candidate(resume_control.get("source_path"), target=False)
        append_path_candidate(
            resume_control.get("target_path") or request.target_path, target=True
        )
    elif request.target_path:
        append_path_candidate(request.target_path, target=True)

    candidates.extend(explicitly_mentioned_files)
    candidates.extend(request.files)
    candidates.append(request.current_file)

    for file_info in candidates:
        if not file_info:
            continue
        match_keys = _context_file_match_keys(file_info)
        if not match_keys:
            continue
        existing = next((seen[key] for key in match_keys if key in seen), None)
        if existing is not None:
            if file_info.target:
                existing.target = True
            if _is_weak_context_path(existing) and not _is_weak_context_path(file_info):
                existing.path = file_info.path
                existing.name = file_info.name or existing.name
                existing.type = file_info.type or existing.type
            if not existing.content and file_info.content:
                existing.content = file_info.content
            if not existing.name and file_info.name:
                existing.name = file_info.name
            if not existing.type and file_info.type:
                existing.type = file_info.type
            if not existing.path and file_info.path:
                existing.path = file_info.path
            continue
        result.append(file_info)
        for key in _context_file_seen_keys(file_info):
            seen.setdefault(key, file_info)
    return result


def _context_file_match_keys(file_info: FileTaskFile) -> List[str]:
    primary = _context_file_key(file_info)
    if not _is_weak_context_path(file_info):
        return [primary] if primary else []
    keys = [primary] if primary else []
    alias = _context_file_basename_key(file_info)
    if alias and alias not in keys:
        keys.append(alias)
    return keys


def _context_file_seen_keys(file_info: FileTaskFile) -> List[str]:
    primary = _context_file_key(file_info)
    keys = [primary] if primary else []
    alias = _context_file_basename_key(file_info)
    if alias and alias not in keys:
        keys.append(alias)
    return keys


def _is_weak_context_path(file_info: FileTaskFile) -> bool:
    path_text = str(file_info.path or "").strip()
    if not path_text:
        return True
    normalized = path_text.replace("\\", "/").strip("/")
    return bool(normalized) and "/" not in normalized


def _context_file_basename_key(file_info: FileTaskFile) -> str:
    path_text = str(file_info.path or "").strip().replace("\\", "/").rstrip("/")
    name = str(file_info.name or "").strip() or (
        Path(path_text).name if path_text else ""
    )
    if not name:
        return ""
    return "basename:" + name.casefold()


def _context_file_key(file_info: FileTaskFile) -> str:
    path_text = str(file_info.path or file_info.name or "").strip()
    if path_text:
        try:
            return os.path.normcase(
                str(Path(path_text).expanduser().resolve(strict=False))
            )
        except OSError:
            return path_text.replace("\\", "/").rstrip("/").casefold()
    return str(file_info.content[:80] or "").strip().casefold()


def files_explicitly_mentioned_in_task(
    *,
    workspace_root: Optional[Path],
    task: str,
) -> List[FileTaskFile]:
    if workspace_root is None:
        return []
    task_text = str(task or "").strip()
    if not task_text:
        return []

    task_folded = task_text.replace("\\", "/").casefold()
    exact_matches: Dict[str, Path] = {}
    basename_matches: Dict[str, List[Path]] = {}
    output_reference_names = _strong_output_reference_file_names(task_text)

    try:
        workspace_files = workspace_root.rglob("*")
        for path in workspace_files:
            if not path.is_file():
                continue
            if path.suffix.casefold() not in _TASK_TEXT_FILE_EXTENSIONS:
                continue
            try:
                rel_path = path.relative_to(workspace_root).as_posix()
            except ValueError:
                continue
            rel_folded = rel_path.casefold()
            name_folded = path.name.casefold()
            if task_text_mentions_path(
                task_folded, rel_folded
            ) or task_text_mentions_path(task_folded, f"workspace/{rel_folded}"):
                if name_folded in output_reference_names:
                    continue
                exact_matches[str(path.resolve()).casefold()] = path
                continue
            if name_folded and name_folded in task_folded:
                if name_folded in output_reference_names:
                    continue
                basename_matches.setdefault(name_folded, []).append(path)
    except OSError as exc:
        logger.debug("[FileTaskRuntime] workspace task-file scan skipped: %s", exc)
        return []

    for matches in basename_matches.values():
        unique_paths = {str(item.resolve()).casefold(): item for item in matches}
        if len(unique_paths) == 1:
            path = next(iter(unique_paths.values()))
            exact_matches.setdefault(str(path.resolve()).casefold(), path)

    resolved: List[FileTaskFile] = []
    for path in exact_matches.values():
        resolved.append(
            FileTaskFile(
                path=str(path.resolve()),
                name=path.name,
                type=path.suffix.lower().lstrip("."),
            )
        )
    resolved.extend(
        _weak_files_explicitly_mentioned_in_task(
            task_text,
            output_reference_names=output_reference_names,
            workspace_reference_names={
                *basename_matches.keys(),
                *(path.name.casefold() for path in exact_matches.values()),
            },
            existing_keys={
                key
                for item in resolved
                for key in _context_file_seen_keys(item)
                if key
            },
        )
    )
    return resolved


def _weak_files_explicitly_mentioned_in_task(
    task_text: str,
    *,
    output_reference_names: set[str],
    workspace_reference_names: set[str],
    existing_keys: set[str],
) -> List[FileTaskFile]:
    result: List[FileTaskFile] = []
    seen = set(existing_keys)
    for match in _TASK_TEXT_FILE_REFERENCE_PATTERN.finditer(task_text):
        raw_path = match.group("path").strip(" \t\r\n,，。；;、!?！？()（）[]【】\"'")
        normalized_path = raw_path.replace("\\", "/").rstrip("/")
        suffix = Path(normalized_path).suffix.lower().lstrip(".")
        if suffix not in _TASK_TEXT_FILE_EXTENSIONS and f".{suffix}" not in _TASK_TEXT_FILE_EXTENSIONS:
            continue
        name = Path(normalized_path).name
        if name.casefold() in output_reference_names:
            continue
        if any(
            name.casefold().endswith(workspace_name)
            for workspace_name in workspace_reference_names
        ):
            continue
        file_info = FileTaskFile(path=raw_path, name=name, type=suffix, target=False)
        key = _context_file_key(file_info)
        basename_key = _context_file_basename_key(file_info)
        if key in seen or (basename_key and basename_key in seen):
            continue
        seen.update(item for item in (key, basename_key) if item)
        result.append(file_info)
    return result


def resolved_workspace_root(workspace_root: str) -> Optional[Path]:
    root_text = str(workspace_root or "").strip()
    if not root_text:
        return None
    try:
        root = Path(root_text).expanduser().resolve()
    except OSError:
        return None
    return root if root.is_dir() else None


def task_text_mentions_path(task_text: str, rel_path: str) -> bool:
    if not rel_path:
        return False
    if rel_path in task_text:
        return True
    basename = rel_path.rsplit("/", 1)[-1]
    if "/" not in rel_path or not basename:
        return False
    compact_task = re.sub(r"\s+", "", task_text)
    compact_rel = re.sub(r"\s+", "", rel_path)
    return bool(compact_rel and compact_rel in compact_task)


def protected_source_write_block_message(
    *,
    tool_name: str,
    tool_args: Dict[str, Any],
    request: FileTaskRequest,
    files: List[FileTaskFile],
    has_source_scoped_write_negation: BoolPredicate,
    has_artifact_creation_intent: BoolPredicate,
    same_path: PathComparator,
) -> str:
    if tool_name == "run_python_code" or not is_write_tool(tool_name):
        return ""
    task_text = str(request.task or "")
    if not (
        has_source_scoped_write_negation(task_text)
        and has_artifact_creation_intent(task_text)
    ):
        return ""
    target = write_target_for_tool(tool_name, tool_args)
    if not target:
        return ""
    if same_path(target, request.target_path):
        return ""
    protected = [
        file_info
        for file_info in files or []
        if file_info
        and str(file_info.path or file_info.name or "").strip()
        and not same_path(
            str(file_info.path or file_info.name or "").strip(),
            request.target_path,
        )
    ]
    for file_info in protected:
        protected_path = str(file_info.path or file_info.name or "").strip()
        if same_path(target, protected_path):
            return (
                f"监管层阻止写入：用户要求保护原文件/源文件，{tool_name} 不能写入 "
                f"{Path(protected_path).name}。请只读取该源文件，并把产物写入目标文件 "
                f"{request.target_path or '用户指定的新文件'}。"
            )
    return ""
