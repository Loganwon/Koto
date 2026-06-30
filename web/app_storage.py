from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppStoragePaths:
    workspace_dir: str
    chat_dir: str
    upload_dir: str


def resolve_app_storage_paths(
    project_root: str,
    workspace_dir: str,
    chats_dir: str | None = None,
) -> AppStoragePaths:
    """Resolve core runtime storage paths and ensure they exist."""
    chat_dir = chats_dir or os.path.join(project_root, "chats")
    upload_dir = os.path.join(project_root, "web", "uploads")

    os.makedirs(chat_dir, exist_ok=True)
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(upload_dir, exist_ok=True)

    return AppStoragePaths(
        workspace_dir=workspace_dir,
        chat_dir=chat_dir,
        upload_dir=upload_dir,
    )