"""Read-only response-quality API backed by the canonical rating store."""

from __future__ import annotations

from flask import Blueprint, jsonify

response_bp = Blueprint("response", __name__)


@response_bp.route("/api/response/stats", methods=["GET"])
def response_stats():
    """Return aggregate user ratings and model self-evaluations."""
    try:
        from app.core.learning.rating_store import get_rating_store

        return jsonify(get_rating_store().get_stats())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@response_bp.route("/api/response/<msg_id>", methods=["GET"])
def response_detail(msg_id: str):
    """Return the user rating, model evaluation, and combined score for one reply."""
    try:
        from app.core.learning.rating_store import get_rating_store

        store = get_rating_store()
        return jsonify(
            {
                "user_rating": store.user_rating_for(msg_id),
                "model_eval": store.model_eval_for(msg_id),
                "combined": store.combined_score(msg_id),
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
