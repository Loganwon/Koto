from __future__ import annotations

import logging
import os
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file


ppt_legacy_bp = Blueprint("ppt_legacy", __name__)
_logger = logging.getLogger("koto.routes.ppt_legacy")


def _workspace_dir() -> str:
    from web.runtime_context import get_workspace_dir

    return get_workspace_dir()


@ppt_legacy_bp.route("/api/ppt/download", methods=["POST"])
def download_ppt():
    """Download a legacy generated PPTX file by session_id."""
    try:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        if not session_id:
            return jsonify({"error": "Missing session_id"}), 400

        from web.ppt_session_manager import PPTSessionManager

        workspace_dir = _workspace_dir()
        ppt_session_dir = os.path.join(workspace_dir, "workspace", "ppt_sessions")
        manager = PPTSessionManager(ppt_session_dir)

        session_data = manager.load_session(session_id)
        if not session_data:
            return jsonify({"error": "Session not found"}), 404

        ppt_file_path = session_data.get("ppt_file_path")
        if not ppt_file_path:
            return jsonify({"error": "PPT file not generated yet"}), 400

        full_path = os.path.join(
            workspace_dir,
            ppt_file_path.lstrip("/").replace("/", os.sep),
        )
        if not os.path.exists(full_path):
            return jsonify({"error": "PPT file not found"}), 404

        return send_file(
            full_path,
            mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            as_attachment=True,
            download_name=os.path.basename(full_path),
        )
    except Exception as exc:
        _logger.info("[PPT DOWNLOAD] error: %s", exc)
        return jsonify({"error": f"Download failed: {exc}"}), 500


@ppt_legacy_bp.route("/api/ppt/generate", methods=["POST"])
def ppt_generate():
    """Generate a PPTX from outline or content using the legacy endpoint."""
    try:
        data = request.get_json(silent=True) or {}
        title = data.get("title", "演示文稿")
        subtitle = data.get("subtitle", "")
        outline = data.get("outline")
        content = data.get("content")
        theme = data.get("theme", "business")
        output_filename = data.get(
            "output_filename",
            f'{title}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pptx',
        )

        output_dir = os.path.join(_workspace_dir(), "documents")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        from web.ppt_generator import PPTGenerator

        generator = PPTGenerator(theme=theme)
        if outline:
            result = generator.generate_from_outline(
                title,
                outline,
                output_path,
                subtitle=subtitle,
            )
        elif content:
            result = generator.generate_from_text(content, output_path, title)
        else:
            return jsonify({"success": False, "error": "需要提供outline或content"}), 400

        return jsonify(result)
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
