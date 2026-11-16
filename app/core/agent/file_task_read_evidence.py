"""Pure helpers for proving that read-only file requests consumed their inputs."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import Any, Dict, List

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_runtime_utils import _is_error_result, _json_payload
from app.core.agent.file_task_targeting import (
    _candidate_path_is_immediate_source_reference,
    _path_with_split_output_directory,
    explicit_output_paths_from_task,
    task_file_reference_spans,
)

_FILE_CONTEXT_PATTERN = re.compile(
    r"\.(?:csv|docx?|md|pdf|pptx?|txt|xlsx?)(?=$|[^\w])",
    re.IGNORECASE,
)
_CONTENT_READ_TOOLS = frozenset(
    {
        "parse_file_to_text",
        "read_sheet_data",
        "read_docx_content",
        "read_file_range",
        "inspect_workbook_structure",
        "audit_financial_workbook",
    }
)


def readonly_task_requires_file_context(
    request: FileTaskRequest, context_files: List[FileTaskFile]
) -> bool:
    if context_files or request.current_file or request.files:
        return True
    if str(request.target_path or "").strip():
        return True
    return bool(_FILE_CONTEXT_PATTERN.search(str(request.task or "")))


def file_references_in_task_text(task: str, known_paths=()) -> List[str]:
    references: List[str] = []
    seen: set[str] = set()
    for reference, _, _ in task_file_reference_spans(task, known_paths):
        normalized = _normalized_path(reference)
        if reference and normalized not in seen:
            seen.add(normalized)
            references.append(reference)
    return references


def _normalized_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/").casefold()
    return posixpath.normpath(text) if text else ""


def _successful_read_record(record: Dict[str, Any], *, tool_output=False) -> bool:
    if _is_error_result(record):
        return False
    if not tool_output:
        # New snippets come only from successful reads. Replayed legacy
        # snippets may contain the parser's bare error instead of content.
        if record.get("success") is True or record.get("ok") is True:
            return True
        return not _is_error_result(record.get("preview"))
    if record.get("result") is None or _is_error_result(record["result"]):
        return False
    payload = _json_payload(record["result"])
    return payload.get("ok") is not False and payload.get("success") is not False


def explicit_file_reference_was_read(
    reference: str,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    *,
    known_paths=(),
) -> bool:
    ref_norm = _normalized_path(reference)
    ref_name = Path(ref_norm).name
    bound = {
        normalized
        for value in known_paths
        if (normalized := _normalized_path(value)) and Path(normalized).name == ref_name
    }
    if "/" not in ref_norm and len(bound) > 1:
        return False
    if "/" in ref_norm and not re.match(r"^(?:[a-z]:/|/)", ref_norm):
        bound = {
            path for path in bound if path == ref_norm or path.endswith("/" + ref_norm)
        }
        if len(bound) == 1:
            expected = next(iter(bound))
        else:
            expected = ref_norm
    else:
        expected = (
            next(iter(bound)) if "/" not in ref_norm and len(bound) == 1 else ref_norm
        )

    def matches_path(value: Any) -> bool:
        text = _normalized_path(value)
        if not text:
            return False
        if text == expected:
            return True
        if expected != ref_norm:
            # A tool may use the bound file's basename, but another full path
            # with the same basename does not prove the selected file was read.
            return text == ref_norm
        return "/" not in ref_norm and Path(text).name == ref_name

    if any(
        _successful_read_record(snippet)
        and matches_path(
            snippet.get("path") or snippet.get("source") or snippet.get("name")
        )
        for snippet in snippets
    ):
        return True
    return any(
        str(output.get("tool_name") or "") in _CONTENT_READ_TOOLS
        and _successful_read_record(output, tool_output=True)
        and isinstance(output.get("args"), dict)
        and any(matches_path(output["args"].get(key)) for key in ("path", "file_path"))
        for output in readonly_tool_outputs
    )


def unsatisfied_explicit_read_file_references(
    request: FileTaskRequest,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
) -> List[str]:
    inventory = [*list(request.files or []), request.current_file]
    known_paths = [str(item.path or item.name or "") for item in inventory if item]
    known_paths.append(str(request.target_path or ""))
    known_names = {_normalized_path(path) for path in known_paths if path}
    known_names.update(Path(path).name for path in tuple(known_names))
    outputs = {
        _normalized_path(path)
        for path in explicit_output_paths_from_task(
            request.task,
            has_artifact_creation_intent=lambda _: True,
            known_target_path=request.target_path or "",
            known_paths=known_paths,
        )
    }
    references = []
    seen = set()
    for reference, start, end in task_file_reference_spans(request.task, known_paths):
        normalized = _normalized_path(reference)
        source_reference = _candidate_path_is_immediate_source_reference(
            request.task[max(0, start - 100) : start],
            request.task[end : end + 100],
            Path(normalized).suffix.lstrip("."),
        )
        if (
            not reference.isascii()
            and normalized not in known_names
            and not (start and request.task[start - 1] in "\"'“‘《「`")
        ):
            # Free prose is resolved by the Kernel's list/read tools. It is
            # not a certain filename contract; the content-evidence gate still
            # requires the model to consume real file results.
            continue
        output_path = _normalized_path(
            _path_with_split_output_directory(
                request.task,
                reference,
                start,
                end,
            )
        )
        if (normalized in outputs or output_path in outputs) and not source_reference:
            continue
        if normalized not in seen:
            seen.add(normalized)
            references.append(reference)
    satisfied = {
        reference
        for reference in references
        if explicit_file_reference_was_read(
            reference,
            snippets,
            readonly_tool_outputs,
            known_paths=[
                str(item.path or item.name or "") for item in inventory if item
            ],
        )
    }
    return [reference for reference in references if reference not in satisfied]


__all__ = [
    "explicit_file_reference_was_read",
    "file_references_in_task_text",
    "readonly_task_requires_file_context",
    "unsatisfied_explicit_read_file_references",
]
