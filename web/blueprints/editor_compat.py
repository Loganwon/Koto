# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Compatibility routes for the bundled legacy editor shell."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from flask import Blueprint, jsonify, request

from web.runtime_context import safe_editor_sse
from web.sse.protocol import sse

editor_compat_bp = Blueprint("editor_compat", __name__)


def _sse_response(chunks):
    from flask import Response, stream_with_context

    return Response(
        stream_with_context(chunks),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@editor_compat_bp.route("/api/editor/docs", methods=["GET"])
def editor_docs_index():
    """Return an empty document index for the bundled editor entrypoint."""
    return jsonify({"ok": True, "docs": []})


@editor_compat_bp.route("/api/editor/ai/analyze", methods=["POST"])
def editor_ai_analyze():
    """Return a lightweight document profile for editor context chips."""
    data = request.get_json(silent=True) or {}
    full_text = str(data.get("full_text") or data.get("text") or "").strip()
    if not full_text:
        return jsonify(
            {"summary": "", "doc_type": "文档", "word_count": 0, "structure": []}
        )

    compact = re.sub(r"\s+", " ", full_text)
    headings = [
        line.strip().lstrip("#").strip()
        for line in full_text.splitlines()
        if line.strip().startswith("#")
    ][:8]
    if not headings:
        headings = [
            line.strip()[:80]
            for line in full_text.splitlines()
            if len(line.strip()) >= 8
        ][:4]
    return jsonify(
        {
            "summary": compact[:160].strip(),
            "doc_type": "文档",
            "word_count": len(full_text),
            "structure": headings,
        }
    )


@editor_compat_bp.route("/api/editor/ai/skill-upload", methods=["POST"])
def editor_ai_skill_upload():
    """Accept editor skill attachments and return temporary path handles."""
    upload_dir = Path(tempfile.gettempdir()) / "koto-editor-skill-uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    files = request.files.getlist("files[]") or list(request.files.values())
    paths = []
    for uploaded in files:
        name = Path(uploaded.filename or "upload.bin").name
        target = upload_dir / name
        uploaded.save(target)
        paths.append(str(target))
    return jsonify({"success": True, "paths": paths})


@editor_compat_bp.route("/api/editor/ai/skill-execute", methods=["POST"])
def editor_ai_skill_execute():
    """Compatibility SSE endpoint for legacy editor skill execution."""
    data = request.get_json(silent=True) or {}
    skill_id = str(data.get("skill_id") or "").strip()

    def generate():
        yield safe_editor_sse({"type": "status", "text": "连接技能运行时"})
        if not skill_id:
            yield safe_editor_sse({"type": "error", "text": "缺少 skill_id"})
            return
        yield sse.chunk(
            {
                "type": "output",
                "output_type": "text",
                "data": f"技能 {skill_id} 已接收，当前兼容入口未产生额外输出。",
            }
        )
        yield safe_editor_sse({"type": "done", "summary": "技能入口已完成"})

    return _sse_response(generate())
