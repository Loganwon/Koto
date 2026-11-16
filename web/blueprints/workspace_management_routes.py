# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Workspace and absolute-filesystem management HTTP routes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Collection

from flask import Blueprint, jsonify, request

from app.core.file_assistant import (
    WorkspaceFsError,
    WorkspaceFsService,
    WorkspaceTreeService,
)

logger = logging.getLogger(__name__)


def register_workspace_management_routes(
    blueprint: Blueprint,
    *,
    workspace_fs: WorkspaceFsService,
    workspace_tree: WorkspaceTreeService,
    workspace_dir: Callable[[], str],
    allowed_extensions: Collection[str],
    seed_new_file: Callable[[Path], None],
    fs_guard: Callable[[Path | str], bool],
) -> None:
    """Register workspace mutation and filesystem-browser routes."""
    workspace_assistant_bp = blueprint
    _WORKSPACE_FS = workspace_fs
    _WORKSPACE_TREE = workspace_tree
    _workspace_dir = workspace_dir
    _ALLOWED_EXT = allowed_extensions
    _seed_new_file = seed_new_file
    _fs_guard = fs_guard

    @workspace_assistant_bp.route("/api/v1/workspace/file", methods=["DELETE"])
    def delete_workspace_file():
        """
        删除工作区中的一个文件（用于左侧面板的 × 按钮）。
        Query param:  path=relative/path/to/file
        """
        filepath = request.args.get("path", "").strip()
        try:
            _WORKSPACE_FS.delete_file(
                workspace_dir=_workspace_dir(),
                rel_path=filepath,
                allowed_extensions=_ALLOWED_EXT,
            )
        except WorkspaceFsError as exc:
            return (jsonify({"error": str(exc)}), exc.status_code)
        return jsonify({"ok": True})

    @workspace_assistant_bp.route("/api/v1/workspace/rename", methods=["PATCH"])
    def rename_workspace_file():
        """
        重命名工作区文件。
        Body (JSON): {"path": "uploads/old.docx", "name": "new_name.docx"}
        Extension must stay the same; new_name must not contain path separators.
        """
        body = request.get_json(silent=True) or {}
        old_path = body.get("path", "").strip()
        new_name = body.get("name", "").strip()
        try:
            result = _WORKSPACE_FS.rename(
                workspace_dir=_workspace_dir(), rel_path=old_path, new_name=new_name
            )
        except WorkspaceFsError as exc:
            return (jsonify({"error": str(exc)}), exc.status_code)
        logger.info("[WorkspaceAssistant] 重命名: %s -> %s", old_path, result.path)
        return jsonify({"ok": True, "path": result.path, "name": result.name})

    @workspace_assistant_bp.route("/api/v1/workspace/folder", methods=["DELETE"])
    def delete_workspace_folder():
        """
        递归删除工作区中的一个文件夹。
        Query param:  path=relative/path/to/folder
        """
        folderpath = request.args.get("path", "").strip()
        try:
            _WORKSPACE_FS.delete_folder(
                workspace_dir=_workspace_dir(), rel_path=folderpath
            )
        except WorkspaceFsError as exc:
            return (jsonify({"error": str(exc)}), exc.status_code)
        return jsonify({"ok": True})

    @workspace_assistant_bp.route("/api/v1/workspace/create_file", methods=["POST"])
    def create_workspace_file():
        """
        在工作区指定目录创建一个新文件（空文件）。
        Body (JSON): {"folder": "relative/path", "name": "filename.txt"}
        folder 为 "" 时在工作区根目录创建。
        """
        body = request.get_json(force=True, silent=True) or {}
        folder = (body.get("folder") or "").strip().strip("/")
        name = (body.get("name") or "").strip()
        try:
            result = _WORKSPACE_FS.create_file(
                workspace_dir=_workspace_dir(),
                folder=folder,
                name=name,
                allowed_extensions=_ALLOWED_EXT,
                seed_file=_seed_new_file,
            )
        except WorkspaceFsError as exc:
            return (jsonify({"error": str(exc)}), exc.status_code)
        logger.info("[WorkspaceAssistant] 创建文件: %s", result.path)
        return jsonify({"ok": True, "path": result.path, "name": result.name})

    @workspace_assistant_bp.route("/api/v1/workspace/create_folder", methods=["POST"])
    def create_workspace_folder():
        """
        在工作区指定目录创建一个新文件夹。
        Body (JSON): {"parent": "relative/path", "name": "foldername"}
        parent 为 "" 时在工作区根目录创建。
        """
        body = request.get_json(force=True, silent=True) or {}
        parent_rel = (body.get("parent") or "").strip().strip("/")
        name = (body.get("name") or "").strip()
        try:
            result = _WORKSPACE_FS.create_folder(
                workspace_dir=_workspace_dir(), parent_rel=parent_rel, name=name
            )
        except WorkspaceFsError as exc:
            return (jsonify({"error": str(exc)}), exc.status_code)
        logger.info("[WorkspaceAssistant] 创建文件夹: %s", result.path)
        return jsonify({"ok": True, "path": result.path, "name": result.name})

    @workspace_assistant_bp.route(
        "/api/v1/workspace/set_workspace_dir", methods=["POST"]
    )
    def set_workspace_dir_endpoint():
        """
        将工作区根目录切换到指定的本地文件夹。
        Body (JSON): {"path": "/absolute/path/to/folder"}
        持久化到 config/user_settings.json 并立即生效（无需重启）。
        """
        body = request.get_json(force=True, silent=True) or {}
        new_path = (body.get("path") or "").strip()
        if not new_path:
            return (jsonify({"error": "缺少 path 字段"}), 400)
        if not _fs_guard(new_path):
            return (jsonify({"error": "不允许将系统路径设为工作区"}), 403)
        target = Path(new_path).resolve()
        if not _fs_guard(target):
            return (jsonify({"error": "不允许将系统路径设为工作区"}), 403)
        if not target.exists():
            try:
                target.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return (jsonify({"error": f"无法创建目录: {e}"}), 400)
        if not target.is_dir():
            return (jsonify({"error": "路径不是文件夹"}), 400)
        from app.core.config.settings_store import atomic_update_settings
        from app.core.config.user_settings import DEFAULT_SETTINGS
        from web.shared import clear_user_settings_cache, get_user_settings_path

        try:
            atomic_update_settings(
                get_user_settings_path(),
                {"storage": {"workspace_dir": str(target)}},
                defaults=DEFAULT_SETTINGS,
            )
        except Exception as e:
            return (jsonify({"error": f"设置保存失败: {e}"}), 500)
        clear_user_settings_cache()
        from web.shared import update_workspace_root

        update_workspace_root(str(target))
        logger.info("[WorkspaceAssistant] 工作区已切换: %s", target)
        return jsonify({"ok": True, "path": str(target), "name": target.name})

    @workspace_assistant_bp.route("/api/v1/workspace/ollama-status")
    def ollama_status():
        """Return local runtime state plus the selected model's tool capability."""
        try:
            import requests as _req
            from app.core.llm.local_model_capabilities import local_model_supports_tools

            r = _req.get(
                "http://127.0.0.1:11434/api/tags",
                timeout=3,
                proxies={"http": None, "https": None},
            )
            data = r.json()
            models = [m["name"] for m in data.get("models", [])]
            if not models:
                return jsonify(
                    {
                        "running": True,
                        "model": None,
                        "models": [],
                        "configured_model": None,
                        "configured_model_installed": False,
                        "configured_model_supports_tools": None,
                    }
                )

            def _status_payload(selected_model: str, configured_model: str = ""):
                resolved_configured = str(
                    configured_model or selected_model or ""
                ).strip()
                return {
                    "running": True,
                    "model": selected_model,
                    "models": models,
                    "configured_model": resolved_configured or None,
                    "configured_model_installed": resolved_configured in models,
                    "configured_model_supports_tools": local_model_supports_tools(
                        resolved_configured
                    ),
                }

            try:
                from app.core.config.user_settings import SettingsManager

                _cfg = SettingsManager().get_all()
                _configured = (
                    _cfg.get("local_model")
                    or _cfg.get("ai", {}).get("local_model")
                    or ""
                ).strip()
                if _configured and _configured in models:
                    return jsonify(_status_payload(_configured, _configured))
            except Exception:
                pass
            preferred = next(
                (
                    m
                    for m in models
                    if any(
                        (
                            k in m.lower()
                            for k in ("9b", "7b", "8b", "13b", "14b", "32b", "70b")
                        )
                    )
                ),
                models[0],
            )
            return jsonify(_status_payload(preferred))
        except Exception:
            return jsonify(
                {
                    "running": False,
                    "model": None,
                    "models": [],
                    "configured_model": None,
                    "configured_model_installed": False,
                    "configured_model_supports_tools": None,
                }
            )

    @workspace_assistant_bp.route("/api/v1/workspace/browse_local")
    def browse_local():
        """
        Lazy filesystem browser — no WORKSPACE_DIR restriction.
        No path  → drives + quick-access locations (Windows) / home shortcuts (other).
        With path → all files and folders at that absolute path.
        """
        import sys as _sys

        path = request.args.get("path", "").strip()
        _openable = frozenset(_ALLOWED_EXT)
        if not path:
            try:
                from web.blueprints.workspace import (
                    _list_drives,
                    _quick_access_locations,
                )

                return jsonify(
                    {
                        "is_root": True,
                        "drives": _list_drives(),
                        "quick_access": _quick_access_locations(),
                    }
                )
            except Exception as e:
                home = Path.home()
                return jsonify(
                    {
                        "is_root": True,
                        "quick_access": [
                            {"name": "主目录", "path": str(home), "type": "quick"}
                        ],
                        "drives": [],
                    }
                )
        target = Path(path).resolve()
        if not target.exists():
            return (jsonify({"error": "路径不存在"}), 404)
        if not target.is_dir():
            return (jsonify({"error": "不是文件夹"}), 400)
        _SKIP = {
            "__pycache__",
            "node_modules",
            ".git",
            ".venv",
            "venv",
            "$RECYCLE.BIN",
            "System Volume Information",
        }
        entries: list[dict] = []
        try:
            for p in sorted(
                target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())
            ):
                if p.name.startswith(".") or p.name in _SKIP:
                    continue
                if p.is_dir():
                    entries.append({"name": p.name, "path": str(p), "type": "folder"})
                elif p.is_file():
                    entries.append(_WORKSPACE_TREE.file_entry(p, str(p), _openable))
        except PermissionError:
            return (jsonify({"error": "无访问权限", "entries": []}), 403)
        parent = str(target.parent)
        if parent == str(target):
            parent = None
        return jsonify(
            {
                "is_root": False,
                "current": str(target),
                "parent": parent,
                "entries": entries,
            }
        )

    @workspace_assistant_bp.route("/api/v1/fs/create_file", methods=["POST"])
    def fs_create_file():
        """
        Create a file by absolute parent path for the lazy filesystem browser.
        Body (JSON): {"parent": "<absolute folder>", "name": "filename.docx"}
        """
        body = request.get_json(force=True, silent=True) or {}
        parent_raw = (body.get("parent") or "").strip()
        name = (body.get("name") or "").strip()
        try:
            result = _WORKSPACE_FS.create_absolute_file(
                parent_raw=parent_raw,
                name=name,
                allowed_extensions=_ALLOWED_EXT,
                seed_file=_seed_new_file,
                path_guard=_fs_guard,
            )
        except WorkspaceFsError as exc:
            return (jsonify({"error": str(exc)}), exc.status_code)
        logger.info("[Browser] 创建文件: %s", result.path)
        return jsonify({"ok": True, "path": result.path, "name": result.name})

    @workspace_assistant_bp.route("/api/v1/fs/create_folder", methods=["POST"])
    def fs_create_folder():
        """
        Create a folder by absolute parent path for the lazy filesystem browser.
        Body (JSON): {"parent": "<absolute folder>", "name": "foldername"}
        """
        body = request.get_json(force=True, silent=True) or {}
        parent_raw = (body.get("parent") or "").strip()
        name = (body.get("name") or "").strip()
        try:
            result = _WORKSPACE_FS.create_absolute_folder(
                parent_raw=parent_raw, name=name, path_guard=_fs_guard
            )
        except WorkspaceFsError as exc:
            return (jsonify({"error": str(exc)}), exc.status_code)
        logger.info("[Browser] 创建文件夹: %s", result.path)
        return jsonify({"ok": True, "path": result.path, "name": result.name})

    @workspace_assistant_bp.route("/api/v1/workspace/fs_delete", methods=["DELETE"])
    def fs_delete():
        """
        Delete any file or folder by absolute path from the filesystem browser.
        Query param: path=<abs_path>
        """
        path = request.args.get("path", "").strip()
        try:
            _WORKSPACE_FS.delete_absolute_path(raw_path=path, path_guard=_fs_guard)
        except WorkspaceFsError as exc:
            return (jsonify({"error": str(exc)}), exc.status_code)
        logger.info("[Browser] 删除: %s", path)
        return jsonify({"ok": True})

    @workspace_assistant_bp.route("/api/v1/workspace/fs_rename", methods=["PATCH"])
    def fs_rename():
        """
        Rename file or folder by absolute path.
        Body (JSON): {"path": "<abs>", "name": "<new_name>"}
        """
        body = request.get_json(silent=True) or {}
        path = (body.get("path") or "").strip()
        new_name = (body.get("name") or "").strip()
        try:
            result = _WORKSPACE_FS.rename_absolute_path(
                raw_path=path, new_name=new_name, path_guard=_fs_guard
            )
        except WorkspaceFsError as exc:
            return (jsonify({"error": str(exc)}), exc.status_code)
        logger.info("[Browser] 重命名: %s -> %s", path, result.path)
        return jsonify({"ok": True, "name": result.name, "path": result.path})

    @workspace_assistant_bp.route("/api/v1/workspace/fs_copy", methods=["POST"])
    def fs_copy():
        """
        Copy or move a file/folder to a destination directory.
        Body (JSON): {"src": "<abs>", "dst_dir": "<abs_dir>", "move": false}
        """
        body = request.get_json(silent=True) or {}
        src = (body.get("src") or "").strip()
        dst_dir = (body.get("dst_dir") or "").strip()
        do_move = bool(body.get("move", False))
        try:
            result = _WORKSPACE_FS.copy_or_move_absolute_path(
                src_raw=src, dst_dir_raw=dst_dir, move=do_move, path_guard=_fs_guard
            )
        except WorkspaceFsError as exc:
            return (jsonify({"error": str(exc)}), exc.status_code)
        logger.info(
            "[Browser] %s: %s -> %s", "移动" if do_move else "复制", src, result.path
        )
        return jsonify({"ok": True, "name": result.name, "path": result.path})

    @workspace_assistant_bp.route(
        "/api/v1/workspace/upload-to-folder", methods=["POST"]
    )
    def upload_to_folder():
        """
        Receive one or more uploaded files and write them into a filesystem-browser folder.
        Form fields: dest_dir=<absolute folder>, file=<one or more uploads>
        """
        dest_dir = (request.form.get("dest_dir") or "").strip()
        uploaded_files = request.files.getlist("file")
        try:
            saved = _WORKSPACE_FS.upload_to_absolute_folder(
                dest_dir_raw=dest_dir,
                uploaded_files=uploaded_files,
                path_guard=_fs_guard,
            )
        except WorkspaceFsError as exc:
            return (jsonify({"error": str(exc)}), exc.status_code)
        logger.info("[Browser] upload-to-folder: %s files -> %s", len(saved), dest_dir)
        return jsonify(
            {
                "ok": True,
                "saved": [{"name": item.name, "path": item.path} for item in saved],
            }
        )
