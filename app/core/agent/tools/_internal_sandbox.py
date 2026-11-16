"""Internal helpers: sandbox operations."""

from __future__ import annotations

import filecmp
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._internal_backup import _clear_readonly_attribute  # noqa: F401
from ._internal_fs import _get_workspace_root  # noqa: F401


def _fingerprint_file(path: str) -> Dict[str, Any]:
    """Capture a stable fingerprint for later change detection."""
    try:
        stat = os.stat(path)
        digest = hashlib.sha1(usedforsecurity=False)
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return {
            "size": stat.st_size,
            "mtime_ns": getattr(
                stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)
            ),
            "sha1": digest.hexdigest(),
        }
    except OSError:
        return {}


def _fingerprint_changed(path: str, fingerprint: Dict[str, Any]) -> bool:
    """Return True when the file differs from its captured fingerprint."""
    if not path or not fingerprint or not os.path.isfile(path):
        return False
    return _fingerprint_file(path) != fingerprint


def _unique_staged_name(name: str, used_names: set[str]) -> str:
    """Return a unique basename for files mirrored into the sandbox workdir."""
    candidate = os.path.basename(name or "") or "task_file"
    candidate = (
        re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", candidate).strip(" .") or "task_file"
    )
    stem, ext = os.path.splitext(candidate)
    normalized = candidate.lower()
    index = 2
    while normalized in used_names:
        candidate = f"{stem}_{index}{ext}"
        normalized = candidate.lower()
        index += 1
    used_names.add(normalized)
    return candidate


def _stage_task_files_for_sandbox(
    resolved_entries: List[Dict[str, str]], sandbox_dir: str
) -> List[Dict[str, str]]:
    """Copy resolved task files into the sandbox workdir for basename-based access."""
    staged_entries: List[Dict[str, str]] = []
    used_names: set[str] = set()

    for entry in resolved_entries:
        staged_name = _unique_staged_name(entry["display_name"], used_names)
        staged_path = os.path.join(sandbox_dir, staged_name)
        shutil.copy2(entry["source_path"], staged_path)
        staged_entries.append(
            {
                **entry,
                "staged_name": staged_name,
                "staged_path": staged_path,
                "staged_mtime_initial": os.stat(staged_path).st_mtime,
                "staged_fingerprint_initial": _fingerprint_file(staged_path),
            }
        )

    return staged_entries


def _prepend_task_file_context(
    code: str,
    staged_entries: List[Dict[str, str]],
    *,
    output_dir: str = "",
    sandbox_target_path: str = "",
) -> str:
    """Expose task file paths to sandbox code and keep basename access working."""
    absolute_paths = {
        entry["display_name"]: entry["source_path"] for entry in staged_entries
    }
    staged_paths = {
        entry["display_name"]: entry["staged_path"] for entry in staged_entries
    }
    staged_names = [entry["staged_name"] for entry in staged_entries]

    workspace_root = _get_workspace_root()
    normalized_output_dir = _normalize_workspace_relative_path(output_dir)
    output_dir_abs = ""
    if normalized_output_dir:
        output_dir_abs = str(
            (Path(workspace_root) / Path(*normalized_output_dir.split("/"))).resolve()
        )
    preamble = (
        "# Attached task files are mirrored into the sandbox working directory.\n"
        f"TASK_WORKSPACE_ROOT = {json.dumps(workspace_root, ensure_ascii=False)}\n"
        f"TASK_OUTPUT_DIR = {json.dumps(output_dir_abs, ensure_ascii=False)}\n"
        f"TASK_TARGET_PATH = {json.dumps(sandbox_target_path, ensure_ascii=False)}\n"
        "import os as _koto_task_os\n"
        "_koto_task_os.environ['TASK_TARGET_PATH'] = TASK_TARGET_PATH\n"
        "_koto_task_os.environ['TASK_OUTPUT_DIR'] = TASK_OUTPUT_DIR\n"
        f"TASK_SANDBOX_FILE_PATHS = {json.dumps(staged_paths, ensure_ascii=False)}\n"
        f"TASK_FILE_PATHS = {json.dumps(absolute_paths, ensure_ascii=False)}\n"
        f"TASK_SANDBOX_FILES = {json.dumps(staged_names, ensure_ascii=False)}\n"
        "# Prefer TASK_SANDBOX_FILE_PATHS[...] for opening and editing attached files.\n"
        "# If TASK_OUTPUT_DIR is not empty, create new relative output files there.\n"
        "# If TASK_TARGET_PATH is not empty, create or modify the requested target there.\n"
        "# Koto will verify and sync TASK_TARGET_PATH back to the real workspace target.\n"
        "# After modifying an attached file, print: KOTO_MODIFIED:<sandbox_absolute_path>\n"
        "# Koto will sync the staged edit back to the source file automatically.\n"
        "# After creating a file in the workspace, print: KOTO_CREATED:<absolute_path>\n"
        "# TASK_FILE_PATHS is retained only as a compatibility fallback for legacy flows.\n"
        "# e.g. print('KOTO_MODIFIED:' + TASK_SANDBOX_FILE_PATHS['report.docx'])\n"
        "# e.g. print('KOTO_CREATED:' + output_path)\n\n"
    )
    return preamble + code


def _normalize_workspace_relative_path(path: str) -> str:
    candidate = str(path or "").strip().replace("\\", "/")
    if not candidate:
        return ""
    if os.path.isabs(candidate):
        try:
            candidate = str(
                Path(candidate)
                .resolve()
                .relative_to(Path(_get_workspace_root()).resolve())
            ).replace("\\", "/")
        except (OSError, ValueError):
            return ""
    candidate = candidate.lstrip("/")
    if candidate.startswith("workspace/"):
        candidate = candidate[len("workspace/") :]
    parts = [part for part in candidate.split("/") if part and part not in {".", ".."}]
    if not parts:
        return ""
    return "/".join(parts)


def _target_output_candidates(sandbox_dir: str, target_path: str) -> List[Path]:
    rel_target = _normalize_workspace_relative_path(target_path)
    if not rel_target:
        return []
    sandbox_root = Path(sandbox_dir)
    target_rel_path = Path(*rel_target.split("/"))
    candidates = [
        sandbox_root / target_rel_path,
        sandbox_root / "workspace" / target_rel_path,
        sandbox_root / target_rel_path.name,
    ]
    unique: List[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate.resolve(strict=False)))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _workspace_target_path(target_path: str) -> Optional[Path]:
    rel_target = _normalize_workspace_relative_path(target_path)
    if not rel_target:
        return None
    workspace_root = Path(_get_workspace_root()).resolve()
    real_target = (workspace_root / Path(*rel_target.split("/"))).resolve()
    try:
        real_target.relative_to(workspace_root)
    except ValueError:
        return None
    return real_target


def _prepare_sandbox_target_paths(sandbox_dir: str, target_path: str) -> str:
    candidates = _target_output_candidates(sandbox_dir, target_path)
    for candidate in candidates:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
    if not candidates:
        return ""
    preferred = candidates[0]
    real_target = _workspace_target_path(target_path)
    if real_target is not None and real_target.is_file():
        try:
            shutil.copy2(real_target, preferred)
        except OSError:
            return ""
    return str(preferred)


def _sync_target_outputs_from_sandbox(
    sandbox_dir: str,
    result: Dict[str, Any],
    *,
    target_path: str,
    target_existed: bool,
) -> Dict[str, Any]:
    rel_target = _normalize_workspace_relative_path(target_path)
    if not rel_target:
        return result
    real_target = _workspace_target_path(rel_target)
    if real_target is None:
        return result

    source: Optional[Path] = None
    for candidate in _target_output_candidates(sandbox_dir, rel_target):
        try:
            if candidate.is_file():
                source = candidate
                break
        except OSError:
            continue
    if source is None:
        return result

    try:
        if real_target.exists() and filecmp.cmp(
            str(source), str(real_target), shallow=False
        ):
            copied = False
        else:
            real_target.parent.mkdir(parents=True, exist_ok=True)
            if real_target.exists():
                _clear_readonly_attribute(str(real_target))
            shutil.copy2(source, real_target)
            copied = True
    except OSError:
        return result

    from .sandbox import _parse_koto_file_markers  # deferred: avoids import cycle

    updated = dict(result)
    stdout = str(updated.get("stdout") or "")
    markers = _parse_koto_file_markers(stdout)
    marker_kind = "modified" if target_existed else "created"
    existing = {
        os.path.normcase(os.path.abspath(path)) for path in markers.get(marker_kind, [])
    }
    norm_target = os.path.normcase(os.path.abspath(str(real_target)))
    if copied and norm_target not in existing:
        marker_name = "KOTO_MODIFIED" if target_existed else "KOTO_CREATED"
        if stdout and not stdout.endswith("\n"):
            stdout += "\n"
        stdout += f"{marker_name}:{real_target}"
        updated["stdout"] = stdout
    return updated


def _mark_direct_target_mutation(
    result: Dict[str, Any],
    *,
    target: Optional[Path],
    target_existed: bool,
    initial_fingerprint: Dict[str, Any],
) -> Dict[str, Any]:
    """Track a requested target written directly outside the sandbox.

    Generated code sometimes writes to ``TASK_OUTPUT_DIR`` or an absolute target
    path but omits the KOTO_CREATED/KOTO_MODIFIED print marker. The target path is
    authoritative, so a real filesystem mutation there must still enter the
    normal file-change and verification pipeline.
    """
    from .sandbox import _parse_koto_file_markers  # deferred: avoids import cycle

    if target is None:
        return result
    marker_kind = "modified" if target_existed else "created"
    marker_name = "KOTO_MODIFIED" if target_existed else "KOTO_CREATED"
    updated = dict(result)
    stdout = str(updated.get("stdout") or "")
    norm_target = os.path.normcase(os.path.abspath(str(target)))
    existing = {
        os.path.normcase(os.path.abspath(path))
        for path in _parse_koto_file_markers(stdout).get(marker_kind, [])
    }
    mutation_verified = target.is_file() and (
        not target_existed or _fingerprint_changed(str(target), initial_fingerprint)
    )
    if not mutation_verified:
        if norm_target not in existing:
            return result
        kept_lines = []
        for line in stdout.splitlines():
            stripped = line.strip()
            prefix = f"{marker_name}:"
            candidate = (
                stripped[len(prefix) :].strip() if stripped.startswith(prefix) else ""
            )
            if candidate and os.path.isabs(candidate):
                if os.path.normcase(os.path.abspath(candidate)) == norm_target:
                    continue
            kept_lines.append(line)
        updated["stdout"] = "\n".join(kept_lines)
        updated["error"] = (
            str(updated.get("error") or "").strip()
            or f"{marker_name} was emitted, but the requested target did not change"
        )
        return updated
    if norm_target in existing:
        return result
    if stdout and not stdout.endswith("\n"):
        stdout += "\n"
    updated["stdout"] = stdout + f"{marker_name}:{target}"
    return updated


def _copy_sandbox_workspace_file_to_workspace(path: Path, workspace_tmp: Path) -> str:
    """Copy sandbox/workspace/... output back to the real workspace root."""
    try:
        source = path.resolve()
        rel_path = source.relative_to(workspace_tmp.resolve())
    except (OSError, ValueError):
        return ""
    if not rel_path.parts or ".." in rel_path.parts:
        return ""
    target = (Path(_get_workspace_root()) / rel_path).resolve()
    try:
        target.relative_to(Path(_get_workspace_root()).resolve())
    except ValueError:
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return str(target)
