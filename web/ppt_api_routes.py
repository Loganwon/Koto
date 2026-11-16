#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Download endpoint for generated presentations.

Presentation editing is owned exclusively by the unified workspace
``/api/pptx`` surface.  P7 removed the parallel session editor while retaining
the generated-file download contract used by chat results.
"""

import os

from flask import Blueprint, jsonify, send_file

from web.ppt_session_manager import get_ppt_session_manager


ppt_api_bp = Blueprint("ppt_api", __name__, url_prefix="/api/ppt")


def _resolve_ppt_file_path(ppt_file_path: str | None) -> str | None:
    if not ppt_file_path:
        return None
    if os.path.isabs(ppt_file_path):
        return ppt_file_path

    normalized = ppt_file_path.lstrip("/\\").replace("/", os.sep)
    candidates = [os.path.abspath(normalized)]
    try:
        from web.runtime_context import service_registry

        workspace_dir = service_registry.workspace_dir
        if workspace_dir:
            candidates.append(os.path.join(workspace_dir, normalized))
    except Exception:
        pass

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[-1] if candidates else None


@ppt_api_bp.route("/download/<session_id>", methods=["GET"])
def download_pptx(session_id: str):
    """Download the generated PPTX associated with a chat session."""
    try:
        session = get_ppt_session_manager().load_session(session_id)
        if not session:
            return jsonify({"success": False, "error": "会话不存在"}), 404

        ppt_file_path = _resolve_ppt_file_path(session.get("ppt_file_path"))
        if not ppt_file_path or not os.path.exists(ppt_file_path):
            return jsonify({"success": False, "error": "PPT 文件不存在"}), 404

        return send_file(
            ppt_file_path,
            as_attachment=True,
            download_name=os.path.basename(ppt_file_path),
            mimetype=(
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation"
            ),
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
