"""Domain module - Python sandbox tools."""

from __future__ import annotations

import base64
import filecmp
import importlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.agent.file_task_result_markers import (
    KOTO_CREATED_FALLBACK_KEY,
    KOTO_CREATED_RESULT_KEY,
    KOTO_CREATED_RESULT_MARKER,
    KOTO_MODIFIED_FALLBACK_KEY,
    KOTO_MODIFIED_RESULT_KEY,
    KOTO_MODIFIED_RESULT_MARKER,
)

from ..task_tools_common import (
    _SANDBOX_CLEANUP_RETRIES,
    _SANDBOX_CLEANUP_RETRY_DELAY_SECONDS,
    _WORKSPACE_CREATED_FILE_EXTS,
)
from ._internal_backup import _clear_readonly_attribute
from ._internal_fs import _get_workspace_root
from ._internal_normalize import _normalize_positive_int
from ._internal_results import _resolve_task_file_entries
from ._internal_sandbox import (
    _copy_sandbox_workspace_file_to_workspace,
    _fingerprint_changed,
    _fingerprint_file,
    _mark_direct_target_mutation,
    _normalize_workspace_relative_path,
    _prepare_sandbox_target_paths,
    _prepend_task_file_context,
    _stage_task_files_for_sandbox,
    _sync_target_outputs_from_sandbox,
    _workspace_target_path,
)

logger = logging.getLogger(__name__)


def _sync_created_workspace_files_from_sandbox(
    sandbox_dir: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Preserve files created under sandbox/workspace/... before temp cleanup."""
    workspace_tmp = Path(sandbox_dir) / "workspace"
    if not workspace_tmp.is_dir():
        return result

    discovered: List[str] = []
    for path in workspace_tmp.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _WORKSPACE_CREATED_FILE_EXTS:
            continue
        copied = _copy_sandbox_workspace_file_to_workspace(path, workspace_tmp)
        if copied:
            discovered.append(copied)

    if not discovered:
        return result

    updated = dict(result)
    stdout = str(updated.get("stdout") or "")
    existing = {
        os.path.normcase(os.path.abspath(path))
        for path in _parse_koto_file_markers(stdout).get("created", [])
    }
    marker_lines = []
    for path in discovered:
        key = os.path.normcase(os.path.abspath(path))
        if key not in existing:
            marker_lines.append(f"KOTO_CREATED:{path}")
            existing.add(key)
    if marker_lines:
        updated["stdout"] = "\n".join(
            part for part in [stdout.rstrip(), *marker_lines] if part
        )
    return updated


def _workspace_output_dir_path(output_dir: str) -> Optional[Path]:
    rel_dir = _normalize_workspace_relative_path(output_dir)
    if not rel_dir:
        return None
    workspace_root = Path(_get_workspace_root()).resolve()
    target_dir = (workspace_root / Path(*rel_dir.split("/"))).resolve()
    try:
        target_dir.relative_to(workspace_root)
    except ValueError:
        return None
    return target_dir


def _relocate_root_created_files_to_output_dir(
    result: Dict[str, Any],
    *,
    output_dir: str,
) -> Dict[str, Any]:
    target_dir = _workspace_output_dir_path(output_dir)
    if target_dir is None:
        return result
    workspace_root = Path(_get_workspace_root()).resolve()
    markers = _parse_koto_file_markers(str(result.get("stdout") or ""))
    replacements: Dict[str, str] = {}
    for raw_path in markers.get("created", []):
        try:
            source = Path(raw_path).resolve()
            source.relative_to(workspace_root)
        except (OSError, ValueError):
            continue
        if source.parent != workspace_root:
            continue
        if source.suffix.lower() not in _WORKSPACE_CREATED_FILE_EXTS:
            continue
        target = (target_dir / source.name).resolve()
        try:
            target.relative_to(workspace_root)
        except ValueError:
            continue
        if source == target or target.exists() or not source.is_file():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        except OSError:
            continue
        replacements[str(source)] = str(target)

    if not replacements:
        return result
    updated = dict(result)
    stdout = str(updated.get("stdout") or "")
    for source, target in replacements.items():
        stdout = stdout.replace(source, target)
    updated["stdout"] = stdout
    return updated


def _parse_koto_file_markers(stdout: str) -> Dict[str, List[str]]:
    """Extract KOTO_CREATED/KOTO_MODIFIED markers printed by sandbox code."""
    created: List[str] = []
    modified: List[str] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith("KOTO_CREATED:"):
            candidate = line[len("KOTO_CREATED:") :].strip()
            if candidate and os.path.isabs(candidate):
                created.append(candidate)
        elif line.startswith("KOTO_MODIFIED:"):
            candidate = line[len("KOTO_MODIFIED:") :].strip()
            if candidate and os.path.isabs(candidate):
                modified.append(candidate)
    return {"created": created, "modified": modified}


def _canonicalize_koto_markers(
    stdout: str, staged_entries: List[Dict[str, str]]
) -> str:
    """Rewrite staged-file KOTO_MODIFIED markers to their source paths and dedupe them."""
    if not stdout:
        return stdout or ""

    staged_to_source = {
        os.path.normcase(os.path.abspath(str(entry.get("staged_path") or ""))): str(
            entry.get("source_path") or ""
        )
        for entry in staged_entries
        if entry.get("staged_path") and entry.get("source_path")
    }
    seen_created: set[str] = set()
    seen_modified: set[str] = set()
    normalized_lines: List[str] = []

    for raw_line in stdout.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("KOTO_CREATED:"):
            candidate = stripped[len("KOTO_CREATED:") :].strip()
            if candidate and os.path.isabs(candidate):
                normalized = os.path.normcase(os.path.abspath(candidate))
                if normalized not in seen_created:
                    seen_created.add(normalized)
                    normalized_lines.append(
                        f"KOTO_CREATED:{os.path.abspath(candidate)}"
                    )
            continue

        if stripped.startswith("KOTO_MODIFIED:"):
            candidate = stripped[len("KOTO_MODIFIED:") :].strip()
            if candidate and os.path.isabs(candidate):
                normalized_candidate = os.path.normcase(os.path.abspath(candidate))
                rewritten = staged_to_source.get(normalized_candidate, candidate)
                rewritten_abs = os.path.abspath(rewritten)
                normalized_rewritten = os.path.normcase(rewritten_abs)
                if normalized_rewritten not in seen_modified:
                    seen_modified.add(normalized_rewritten)
                    normalized_lines.append(f"KOTO_MODIFIED:{rewritten_abs}")
            continue

        normalized_lines.append(raw_line)

    return "\n".join(normalized_lines)


def _sync_staged_files_to_source(
    staged_entries: List[Dict[str, str]],
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Copy staged-file edits back to source files and emit KOTO_MODIFIED markers."""
    stdout = _canonicalize_koto_markers(str(result.get("stdout") or ""), staged_entries)
    existing_markers = _parse_koto_file_markers(stdout)
    already_reported = {
        os.path.normcase(os.path.abspath(path))
        for path in existing_markers.get("modified", [])
    }
    extra_modified: List[str] = []

    for entry in staged_entries:
        staged_path = str(entry.get("staged_path") or "")
        source_path = str(entry.get("source_path") or "")
        if not staged_path or not source_path or not os.path.isfile(staged_path):
            continue

        staged_changed = _fingerprint_changed(
            staged_path,
            entry.get("staged_fingerprint_initial") or {},
        )
        source_changed = _fingerprint_changed(
            source_path,
            entry.get("source_fingerprint_initial") or {},
        )
        if not staged_changed and not source_changed:
            continue

        files_match_after_run = False
        if staged_changed:
            try:
                files_match_after_run = filecmp.cmp(
                    staged_path, source_path, shallow=False
                )
            except OSError:
                files_match_after_run = False

        if staged_changed and not source_changed:
            try:
                if os.path.exists(source_path):
                    _clear_readonly_attribute(source_path)
                shutil.copy2(staged_path, source_path)
                logger.info(
                    "[sandbox] Auto-synced modified staged file -> %s", source_path
                )
                source_changed = True
            except Exception as exc:
                logger.warning(
                    "[sandbox] Sync failed %s -> %s: %s", staged_path, source_path, exc
                )
                continue
        elif staged_changed and source_changed and not files_match_after_run:
            logger.warning(
                "[sandbox] Source and staged file both changed; keeping direct source version for %s",
                source_path,
            )

        norm_source = os.path.normcase(os.path.abspath(source_path))
        if source_changed and norm_source not in already_reported:
            extra_modified.append(source_path)

    if not extra_modified:
        merged_result = dict(result)
        merged_result["stdout"] = stdout
        return merged_result

    extra_lines = "\n".join(f"KOTO_MODIFIED:{path}" for path in extra_modified)
    merged_stdout = stdout
    if merged_stdout and not merged_stdout.endswith("\n"):
        merged_stdout += "\n"
    merged_stdout += extra_lines

    merged_result = dict(result)
    merged_result["stdout"] = merged_stdout
    return merged_result


def _format_sandbox_result(result: Dict[str, Any]) -> str:
    """Normalize sandbox execution output into a single text payload."""
    parts = []
    if result.get("stdout"):
        parts.append(result["stdout"])
    if result.get("stderr"):
        parts.append(f"[stderr] {result['stderr']}")
    generated_files = result.get("files") or result.get("images") or {}
    if generated_files:
        parts.append(f"[{len(generated_files)} image(s) generated]")
    if result.get("error"):
        parts.append(f"[error] {result['error']}")
    return "\n".join(parts) if parts else "(no output)"


def _load_sandbox_run_python():
    module_name = "app.core.sandbox"
    module = sys.modules.get(module_name)
    if module is not None and not isinstance(module, types.ModuleType):
        sys.modules.pop(module_name, None)

    module = importlib.import_module(module_name)
    run_python = getattr(module, "run_python", None)
    if (
        not callable(run_python)
        or getattr(run_python, "__module__", module_name) != module_name
    ):
        sys.modules.pop(module_name, None)
        module = importlib.import_module(module_name)
        run_python = getattr(module, "run_python", None)

    if not callable(run_python):
        raise RuntimeError("app.core.sandbox.run_python is unavailable")
    return run_python


class SandboxRunResult(dict):
    """Structured sandbox result with a marker-text compatibility view."""

    def _marker_text(self) -> str:
        parts: List[str] = []
        created = (
            self.get(KOTO_CREATED_RESULT_KEY)
            or self.get(KOTO_CREATED_FALLBACK_KEY)
            or []
        )
        modified = (
            self.get(KOTO_MODIFIED_RESULT_KEY)
            or self.get(KOTO_MODIFIED_FALLBACK_KEY)
            or []
        )

        if isinstance(created, list) and created:
            parts.append(
                KOTO_CREATED_RESULT_MARKER + json.dumps(created, ensure_ascii=False)
            )
        if isinstance(modified, list) and modified:
            parts.append(
                KOTO_MODIFIED_RESULT_MARKER + json.dumps(modified, ensure_ascii=False)
            )
        return "\n".join(parts)

    def as_text(self) -> str:
        text = str(self.get("summary") or "")
        marker_text = self._marker_text()
        if marker_text:
            if text and not text.endswith("\n"):
                text += "\n"
            text += marker_text
        return text

    def _legacy_marker_text(self) -> str:
        return self._marker_text()

    def as_legacy_text(self) -> str:
        return self.as_text()

    def __contains__(self, item: object) -> bool:
        if dict.__contains__(self, item):
            return True
        if isinstance(item, str):
            return item in self.as_text()
        return False

    def __str__(self) -> str:
        return self.as_text()


def run_python_in_sandbox(
    code: str,
    timeout: int = 30,
    task_files: Optional[List[Dict[str, str]]] = None,
    target_path: str = "",
    output_dir: str = "",
) -> Dict[str, Any]:
    """Execute Python code in the sandbox. Returns structured stdout/stderr/files.

    If the code prints ``KOTO_CREATED:<absolute_path>`` or
    ``KOTO_MODIFIED:<absolute_path>`` lines, those paths are returned as hidden
    structured fields so the file-task runtime can emit file_change events.
    """
    tmpdir: str | None = None
    normalized_timeout = _normalize_positive_int(timeout, default=30, upper=120)
    try:
        run_python = _load_sandbox_run_python()
        resolved_task_files = _resolve_task_file_entries(task_files)
        tmpdir = tempfile.mkdtemp(prefix="koto-task-")
        staged_entries: List[Dict[str, str]] = []
        if resolved_task_files:
            staged_entries = _stage_task_files_for_sandbox(resolved_task_files, tmpdir)
        resolved_target = _workspace_target_path(target_path)
        target_existed = bool(resolved_target and resolved_target.is_file())
        target_fingerprint_initial = (
            _fingerprint_file(str(resolved_target)) if target_existed else {}
        )
        sandbox_target_path = _prepare_sandbox_target_paths(tmpdir, target_path)
        prepared_code = _prepend_task_file_context(
            code,
            staged_entries,
            output_dir=output_dir,
            sandbox_target_path=sandbox_target_path,
        )
        result = run_python(prepared_code, timeout=normalized_timeout, work_dir=tmpdir)
        result = _sync_target_outputs_from_sandbox(
            tmpdir,
            result,
            target_path=target_path,
            target_existed=target_existed,
        )
        result = _mark_direct_target_mutation(
            result,
            target=resolved_target,
            target_existed=target_existed,
            initial_fingerprint=target_fingerprint_initial,
        )
        result = _sync_created_workspace_files_from_sandbox(tmpdir, result)
        result = _relocate_root_created_files_to_output_dir(
            result,
            output_dir=output_dir,
        )
        if staged_entries:
            result = _sync_staged_files_to_source(staged_entries, result)
        return _wrap_sandbox_result(result, output_dir=output_dir)
    except Exception as e:
        return SandboxRunResult(
            {
                "summary": f"Sandbox error: {e}",
                "stdout": "",
                "stderr": "",
                "error": str(e),
                "files": {},
                "_koto_created": [],
                "_koto_modified": [],
                "__koto_created__": [],
                "__koto_modified__": [],
            }
        )
    finally:
        if tmpdir and os.path.isdir(tmpdir):
            _cleanup_sandbox_tmpdir(tmpdir)


def _cleanup_sandbox_tmpdir(tmpdir: str) -> None:
    last_error: OSError | None = None
    for attempt in range(1, _SANDBOX_CLEANUP_RETRIES + 1):
        try:
            shutil.rmtree(tmpdir)
            return
        except OSError as exc:
            last_error = exc
            if attempt >= _SANDBOX_CLEANUP_RETRIES:
                break
            time.sleep(_SANDBOX_CLEANUP_RETRY_DELAY_SECONDS)
    if last_error is not None:
        # Try to quarantine the dir so it is not re-used accidentally (Windows
        # file-locks are a common cause of rmtree failure).
        try:
            dead_name = f".dead.{int(time.time())}.{os.path.basename(tmpdir)}"
            dead_path = os.path.join(os.path.dirname(tmpdir), dead_name)
            os.rename(tmpdir, dead_path)
            logger.warning(
                "[task_tools] sandbox tmpdir cleanup failed; quarantined as %s: %s",
                dead_path,
                last_error,
            )
        except OSError:
            logger.warning(
                "[task_tools] temp sandbox cleanup skipped for %s: %s",
                tmpdir,
                last_error,
            )


def _relocate_materialized_files_to_output_dir(
    materialized_files: Dict[str, str],
    *,
    output_dir: str,
) -> Dict[str, str]:
    target_dir = _workspace_output_dir_path(output_dir)
    if target_dir is None or not materialized_files:
        return materialized_files
    workspace_root = Path(_get_workspace_root()).resolve()
    relocated: Dict[str, str] = {}
    changed = False
    for name, raw_path in materialized_files.items():
        path_text = str(raw_path or "").strip()
        if not path_text:
            continue
        try:
            source = Path(path_text).resolve()
        except OSError:
            relocated[name] = path_text
            continue
        if (
            source.parent != workspace_root
            or source.suffix.lower() not in _WORKSPACE_CREATED_FILE_EXTS
        ):
            relocated[name] = path_text
            continue
        target = (target_dir / source.name).resolve()
        try:
            target.relative_to(workspace_root)
        except ValueError:
            relocated[name] = path_text
            continue
        if source == target:
            relocated[name] = str(source)
            continue
        if target.exists() or not source.is_file():
            relocated[name] = path_text
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        except OSError:
            relocated[name] = path_text
            continue
        relocated[name] = str(target)
        changed = True
    return relocated if changed else materialized_files


def _wrap_sandbox_result(
    result: Dict[str, Any],
    *,
    output_dir: str = "",
) -> Dict[str, Any]:
    """Normalize sandbox result into structured runtime payload."""
    text = _format_sandbox_result(result)
    markers = _parse_koto_file_markers(str(result.get("stdout", "")))
    created = markers.get("created", [])
    modified = markers.get("modified", [])
    generated_files = result.get("files") or result.get("images") or {}
    if not isinstance(generated_files, dict):
        generated_files = {}
    materialized_files = _materialize_sandbox_files(generated_files)
    materialized_files = _relocate_materialized_files_to_output_dir(
        materialized_files,
        output_dir=output_dir,
    )
    # fallback: when stdout has no KOTO_CREATED markers, use sandbox-captured files
    if not created and materialized_files:
        created = list(materialized_files.values())
    return SandboxRunResult(
        {
            "summary": text,
            "stdout": str(result.get("stdout") or ""),
            "stderr": str(result.get("stderr") or ""),
            "error": str(result.get("error") or ""),
            "files": dict(generated_files),
            "generated_file_paths": materialized_files,
            "generated_files": [
                {
                    "name": name,
                    "path": path,
                    "file_type": Path(path).suffix.lstrip(".").lower(),
                }
                for name, path in materialized_files.items()
            ],
            "_koto_created": created,
            "_koto_modified": modified,
            "__koto_created__": created,
            "__koto_modified__": modified,
        }
    )


def _materialize_sandbox_files(files: Dict[str, Any]) -> Dict[str, str]:
    """Persist sandbox-captured files so later tools can consume real paths."""
    materialized: Dict[str, str] = {}
    if not files:
        return materialized
    artifact_dir = tempfile.mkdtemp(prefix="koto-task-artifacts-")
    for raw_name, raw_data in files.items():
        filename = _safe_artifact_filename(str(raw_name or "artifact").strip())
        if not filename:
            filename = "artifact.bin"
        try:
            data = base64.b64decode(str(raw_data or ""), validate=False)
        except Exception:
            continue
        if not data:
            continue
        target = os.path.join(artifact_dir, filename)
        try:
            with open(target, "wb") as fh:
                fh.write(data)
        except OSError:
            continue
        materialized[str(raw_name)] = target
    if not materialized:
        try:
            shutil.rmtree(artifact_dir)
        except OSError:
            pass
    return materialized


def _safe_artifact_filename(filename: str) -> str:
    name = os.path.basename(filename.replace("\\", "/")).strip()
    if not name or name in {".", ".."}:
        return ""
    stem = re.sub(r"[^A-Za-z0-9._ \-\u4e00-\u9fff]", "_", name)
    return stem[:120] or "artifact.bin"
