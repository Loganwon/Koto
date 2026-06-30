# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Token usage statistics routes."""

from __future__ import annotations

import logging

from flask import Blueprint, Response, jsonify, request

_logger = logging.getLogger("koto.routes.token_stats")

token_stats_bp = Blueprint("token_stats", __name__)


@token_stats_bp.route("/api/token-stats", methods=["GET"])
def api_token_stats() -> Response:
    """Return token usage statistics for today, month, models, and recent days."""
    try:
        from web.token_tracker import get_stats

        return jsonify(get_stats())
    except Exception as exc:
        _logger.error("[token_stats] %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@token_stats_bp.route("/api/token-stats/reset", methods=["POST"])
def api_token_stats_reset() -> Response:
    """Reset token usage statistics. Body: {"period": "today" | "month" | "all"}."""
    try:
        from web.token_tracker import reset_stats

        period = (request.json or {}).get("period", "all")
        return jsonify(reset_stats(period))
    except Exception as exc:
        _logger.error("[token_stats_reset] %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500
