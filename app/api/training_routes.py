# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Development-only training data API routes."""

from __future__ import annotations

import logging
import threading

from flask import Blueprint, jsonify, request

from app.core.learning.training_data_builder import TrainingDataBuilder, _OUT_DIR

logger = logging.getLogger(__name__)

training_bp = Blueprint("training", __name__)


@training_bp.route("/api/training/build", methods=["POST"])
def training_build():
    """Trigger training data generation."""
    opts = request.json or {}
    result_holder = {}

    def _run():
        try:
            result_holder["result"] = TrainingDataBuilder.build_all(
                include_routing=opts.get("include_routing", True),
                include_chat=opts.get("include_chat", True),
                include_shadow=opts.get("include_shadow", True),
                include_synthetic=opts.get("include_synthetic", True),
                include_memory=opts.get("include_memory", True),
                min_quality=opts.get("min_quality", 0.5),
                verbose=True,
            )
            result_holder["status"] = "ok"
        except Exception as exc:
            result_holder["status"] = "error"
            result_holder["error"] = str(exc)

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout=60)

    if result_holder.get("status") == "ok":
        return jsonify({"success": True, "data": result_holder["result"]})

    return (
        jsonify({"success": False, "error": result_holder.get("error", "timeout")}),
        500,
    )


@training_bp.route("/api/training/stats", methods=["GET"])
def training_stats():
    """Return generated training data statistics."""
    return jsonify(TrainingDataBuilder.get_stats())


@training_bp.route("/api/ratings/stats", methods=["GET"])
def ratings_stats():
    """Return combined user and model rating statistics."""
    try:
        from app.core.learning.rating_store import get_rating_store

        return jsonify(get_rating_store().get_stats())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@training_bp.route("/api/ratings/sample/<msg_id>", methods=["GET"])
def rating_sample(msg_id: str):
    """Return combined rating details for one message."""
    try:
        from app.core.learning.rating_store import get_rating_store

        rs = get_rating_store()
        return jsonify(
            {
                "user_rating": rs.user_rating_for(msg_id),
                "model_eval": rs.model_eval_for(msg_id),
                "combined": rs.combined_score(msg_id),
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@training_bp.route("/api/training/push-ollama", methods=["POST"])
def training_push_ollama():
    """Generate Ollama model files from the latest training data."""
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    routing_files = sorted(_OUT_DIR.glob("koto_routing_*.jsonl"), reverse=True)
    full_files = sorted(_OUT_DIR.glob("koto_full_*.jsonl"), reverse=True)

    if not routing_files or not full_files:
        return (
            jsonify({"success": False, "error": "请先运行 /api/training/build 生成数据"}),
            400,
        )

    TrainingDataBuilder._push_to_ollama_if_available(
        routing_files[0], full_files[0], verbose=True
    )
    return jsonify(
        {
            "success": True,
            "message": "Modelfile 已生成，查看 workspace/training_data/",
        }
    )
