"""Internal helpers: filesystem paths."""

from __future__ import annotations

import os
from typing import Optional

from app.core.agent.path_utils import (
    default_search_roots,
    has_parent_path_segment,
    is_within_roots,
    resolve_existing_path,
)
from app.core.services.file_service import FileService

from .. import task_tools_common as _task_tools_common


def _get_workspace_root() -> str:
    # Read the shared override live so runtime/test overrides applied to the
    # common module (e.g. task_tools_common._WORKSPACE_ROOT) take effect here.
    if _task_tools_common._WORKSPACE_ROOT is not None:
        return _task_tools_common._WORKSPACE_ROOT
    from app.core.config.workspace_runtime import get_workspace_root

    return get_workspace_root()


def _get_project_root() -> str:
    """Return the project root (parent of workspace)."""
    return os.path.dirname(_get_workspace_root())


def _file_service(*, backup_enabled: bool = False) -> FileService:
    service_cls = _task_tools_common.FileService
    return service_cls(
        workspace_dir=_get_workspace_root(),
        backup_enabled=backup_enabled,
    )


def _safe_resolve(relative_path: str) -> Optional[str]:
    """Resolve a user path inside workspace root or project root.

    Tries workspace root first, then project root as fallback.
    Returns None on traversal or if neither resolves.
    """
    root = _get_workspace_root()
    project_root = _get_project_root()
    # Strip leading "workspace/" prefix — the model sometimes includes it even
    # though paths are already relative to the workspace root.
    stripped = relative_path.replace("\\", "/")
    if has_parent_path_segment(stripped):
        return None
    if stripped.startswith("workspace/"):
        stripped = stripped[len("workspace/") :]
    try:
        resolved = os.path.normpath(os.path.join(root, stripped))
        if not is_within_roots(resolved, [root]):
            try:
                project_resolved = os.path.normpath(
                    os.path.join(project_root, stripped)
                )
                if is_within_roots(project_resolved, [project_root]):
                    return project_resolved
            except (ValueError, TypeError):
                pass
            return None
        if not os.path.exists(resolved):
            try:
                project_resolved = os.path.normpath(
                    os.path.join(project_root, stripped)
                )
                if is_within_roots(project_resolved, [project_root]) and os.path.exists(
                    project_resolved
                ):
                    return project_resolved
            except (ValueError, TypeError):
                pass
        return resolved
    except (ValueError, TypeError):
        return None


def _resolve_path(path: str, *, must_exist: bool = True) -> Optional[str]:
    """Accept both absolute and relative-to-workspace paths.

    Args:
        path: File path, absolute or relative.
        must_exist: If True (default), returns None for non-existent files.
                    If False, returns the resolved path even if the file does not exist yet.
    """
    if os.path.isabs(path):
        normalized = os.path.normpath(path)
        if must_exist and not os.path.exists(normalized):
            return None
        return normalized
    if has_parent_path_segment(path):
        return None

    # Keep workspace-relative priority for backward compatibility.
    ws_candidate = _safe_resolve(path)
    if ws_candidate and os.path.exists(ws_candidate):
        return ws_candidate

    # Try project root as well
    project_root = _get_project_root()
    try:
        project_candidate = os.path.normpath(
            os.path.join(project_root, path.replace("\\", "/"))
        )
        if is_within_roots(project_candidate, [project_root]) and os.path.exists(
            project_candidate
        ):
            return project_candidate
    except (ValueError, TypeError):
        pass

    # For write targets, return the workspace candidate even if it does not exist
    if not must_exist and ws_candidate:
        return ws_candidate

    roots = [_get_workspace_root(), *default_search_roots()]
    resolved, _ = resolve_existing_path(path, roots=roots)
    if resolved and (
        is_within_roots(resolved, [_get_workspace_root()])
        or is_within_roots(resolved, [project_root])
    ):
        return resolved
    # For write targets, try project root as a last resort
    if not must_exist:
        try:
            fallback = os.path.normpath(
                os.path.join(project_root, path.replace("\\", "/"))
            )
            if is_within_roots(fallback, [project_root]):
                return fallback
        except (ValueError, TypeError):
            pass
    return resolved


def _result_path(raw_path: str, resolved_path: str) -> str:
    """Return a workspace-relative path so the frontend can match it to wsSourcePath.

    Falls back to absolute path when the file is outside the workspace root.
    Frontend refresh (_refreshChangedFile) compares this to state.wsSourcePath which
    is always workspace-relative, so returning absolute paths breaks the match.
    """
    target = resolved_path or raw_path
    if not target:
        return raw_path
    ws_root = _get_workspace_root()
    try:
        rel = os.path.relpath(target, ws_root).replace("\\", "/")
        if not rel.startswith(".."):
            return rel
    except (ValueError, TypeError):
        pass
    return target
