# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
AI response feedback API.

Mounted routes:
  POST /api/response/rate  User star-rating for an AI response
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from web.auth import require_auth

logger = logging.getLogger(__name__)

response_bp = Blueprint("response", __name__, url_prefix="/api/response")


@response_bp.route("/rate", methods=["POST"])
@require_auth
def response_rate():
    """Persist a user star rating and optionally record strong positive samples."""
    data = request.json or {}
    msg_id = data.get("msg_id", "")
    stars = int(data.get("stars", 0))
    comment = (data.get("comment") or "").strip()
    session_name = data.get("session_name", "default")
    user_input = data.get("user_input", "")
    ai_response = data.get("ai_response", "")
    task_type = data.get("task_type", "CHAT")

    if not (1 <= stars <= 5):
        return jsonify({"success": False, "error": "stars 必须在 1~5 之间"}), 400

    try:
        from app.core.learning.rating_store import RatingStore

        rs = RatingStore()
        rs.save_user_rating(
            msg_id=msg_id,
            stars=stars,
            comment=comment,
            session_name=session_name,
            user_input=user_input,
            ai_response=ai_response,
        )
    except Exception as exc:
        logger.warning("[ResponseRate] RatingStore 保存失败: %s", exc)

    trace_id = None
    if stars >= 4 and user_input and ai_response:
        try:
            from app.core.learning.shadow_tracer import ShadowTracer

            trace_id = ShadowTracer.record_approved(
                session_id=session_name,
                user_input=user_input,
                ai_response=ai_response,
                skill_id=None,
                task_type=task_type,
                model_used="",
                metadata={"stars": stars, "comment": comment, "source": "user_rating"},
            )
            logger.debug(
                "[ResponseRate] %s stars recorded as trace_id=%s", stars, trace_id
            )
        except Exception as exc:
            logger.warning("[ResponseRate] ShadowTracer 记录失败: %s", exc)

    return jsonify(
        {
            "success": True,
            "msg_id": msg_id,
            "stars": stars,
            "trace_id": trace_id,
            "flywheel": trace_id is not None,
        }
    )
