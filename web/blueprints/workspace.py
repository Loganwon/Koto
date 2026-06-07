# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Workspace file and folder browsing blueprint.

Routes:
  GET    /api/workspace/<path:filepath>  — Serve a file from the workspace
  GET    /api/workspace                  — List files in the workspace root
  GET    /api/browse                     — Browse folders on the local filesystem
"""

import logging
import os
import sys
from flask import Blueprint, Response, jsonify, request, send_from_directory

from web.shared import WORKSPACE_DIR

_logger = logging.getLogger("koto.routes.workspace")

workspace_bp = Blueprint("workspace", __name__)


# ─── Workspace file routes ───────────────────────────────────────────────────


@workspace_bp.route("/api/workspace/<path:filepath>")
def get_workspace_file(filepath: str) -> Response:
    """获取 workspace 中的文件，支持子目录"""
    _logger.debug(f"[API] Serving workspace file: {filepath}")
    full_path = os.path.join(WORKSPACE_DIR, filepath)

    # 安全检查：确保请求的路径在 WORKSPACE_DIR 下
    try:
        resolved_path = os.path.abspath(full_path)
        resolved_workspace = os.path.abspath(WORKSPACE_DIR)
        if not resolved_path.startswith(resolved_workspace):
            _logger.debug(
                f"[API] Security violation: {resolved_path} not under {resolved_workspace}"
            )
            return jsonify({"error": "Access denied"}), 403

        if not os.path.exists(resolved_path):
            _logger.debug(f"[API] File not found: {resolved_path}")
            return jsonify({"error": "File not found"}), 404

        _logger.debug(f"[API] Serving: {resolved_path}")
        return send_from_directory(WORKSPACE_DIR, filepath)
    except Exception as e:
        _logger.debug(f"[API] Error serving {filepath}: {e}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": "Server error", "detail": str(e)}), 500


@workspace_bp.route("/api/workspace", methods=["GET"])
def list_workspace_files() -> Response:
    files = os.listdir(WORKSPACE_DIR)
    return jsonify({"files": files})


# ─── Folder browsing ─────────────────────────────────────────────────────────


def _list_drives():
    """Return list of available drive letters on Windows."""
    drives = []
    if sys.platform == "win32":
        import string
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                import ctypes
                try:
                    drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
                    # 2=removable, 3=fixed, 4=remote/network, 5=CD, 6=ramdisk
                    type_map = {2: "移动磁盘", 3: "本地磁盘", 4: "网络驱动器", 5: "光驱", 6: "RAM"}
                    drive_type_name = type_map.get(drive_type, "磁盘")
                    # Try to get volume label
                    buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.kernel32.GetVolumeInformationW(
                        drive, buf, 256, None, None, None, None, 0
                    )
                    label = buf.value or drive_type_name
                    drives.append({"name": f"{label} ({letter}:)", "path": drive, "type": "drive"})
                except Exception:
                    drives.append({"name": f"本地磁盘 ({letter}:)", "path": drive, "type": "drive"})
    return drives


def _quick_access_locations():
    """Return Windows quick-access shortcuts: Desktop, Documents, Downloads, etc."""
    locations = []
    ws = str(WORKSPACE_DIR)
    if os.path.isdir(ws):
        locations.append({"name": "Koto 工作区", "path": ws, "type": "quick"})
    if sys.platform == "win32":
        home = os.path.expanduser("~")
        shortcuts = [
            ("桌面", os.path.join(home, "Desktop")),
            ("文档", os.path.join(home, "Documents")),
            ("下载", os.path.join(home, "Downloads")),
            ("图片", os.path.join(home, "Pictures")),
            ("视频", os.path.join(home, "Videos")),
            ("音乐", os.path.join(home, "Music")),
            ("用户主目录", home),
        ]
        for label, p in shortcuts:
            if os.path.isdir(p):
                locations.append({"name": label, "path": p, "type": "quick"})
    return locations


@workspace_bp.route("/api/browse/drives", methods=["GET"])
def browse_drives() -> Response:
    """列出所有可用磁盘驱动器及快速访问位置（仅 Windows）。"""
    return jsonify({
        "drives": _list_drives(),
        "quick_access": _quick_access_locations(),
    })


@workspace_bp.route("/api/browse", methods=["GET"])
def browse_folders() -> Response:
    # 当 path 为空时，回退到用户主目录，而不是 C:\
    path = request.args.get("path", "").strip()
    if not path:
        path = os.path.expanduser("~")

    try:
        if not os.path.exists(path):
            return jsonify({"error": "路径不存在", "folders": [], "parent": None})

        if not os.path.isdir(path):
            return jsonify({"error": "不是文件夹", "folders": [], "parent": None})

        folders = []
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    folders.append({"name": item, "path": item_path})
        except PermissionError:
            return jsonify({"error": "没有权限访问", "folders": [], "parent": None})

        folders.sort(key=lambda x: x["name"].lower())

        # Get parent path
        parent = os.path.dirname(path)
        if parent == path:  # Root drive
            parent = None

        return jsonify({"folders": folders, "parent": parent, "current": path})
    except Exception as e:
        return jsonify({"error": str(e), "folders": [], "parent": None})
