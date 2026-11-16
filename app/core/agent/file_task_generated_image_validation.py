"""Completion evidence for images generated during DOCX write tasks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

_IMAGE_ARTIFACT_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp", "gif"}


def pending_generated_docx_images(
    runtime: Any,
    request: Any,
    files: List[Any],
    generated_artifacts: List[Dict[str, Any]],
    file_changes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return generated images that have not been embedded in the DOCX."""

    if not generated_artifacts or not runtime._has_docx_write_target(request, files):
        return []

    inserted_keys: set[str] = set()
    inserted_names: set[str] = set()
    for change in file_changes or []:
        if not isinstance(change, dict):
            continue
        if str(change.get("operation") or "").strip() != "insert_image_into_docx":
            continue
        image_path = str(change.get("image_path") or "").strip()
        image_name = str(change.get("image_name") or "").strip()
        if image_path:
            inserted_keys.add(runtime._generated_image_artifact_key(image_path))
            inserted_names.add(Path(image_path.replace("\\", "/")).name.lower())
        if image_name:
            inserted_names.add(image_name.lower())

    pending: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in generated_artifacts or []:
        if not isinstance(item, dict):
            continue
        artifact = dict(item)
        kind = str(artifact.get("kind") or "").strip().lower()
        path = str(artifact.get("path") or "").strip()
        name = runtime._generated_image_artifact_name(artifact)
        extension = Path(name or path).suffix.lstrip(".").lower()
        if kind != "image" or extension not in _IMAGE_ARTIFACT_EXTENSIONS:
            continue
        resolved_path = runtime._resolve_task_file_path(path) if path else ""
        if path and not (resolved_path or os.path.exists(path)):
            continue
        if resolved_path:
            artifact["path"] = resolved_path
        key = runtime._generated_image_artifact_key(resolved_path or path or name)
        name_key = name.lower()
        if key in inserted_keys or name_key in inserted_names:
            continue
        if key in seen or name_key in seen:
            continue
        seen.add(key or name_key)
        pending.append(artifact)
    return pending


__all__ = ["pending_generated_docx_images"]
