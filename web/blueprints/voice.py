# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Voice blueprint with only the supported upload-based STT surface."""

from __future__ import annotations

import base64
import json
import logging

from flask import Blueprint, jsonify, request

_logger = logging.getLogger("koto.routes.voice")

voice_bp = Blueprint("voice_routes", __name__)


@voice_bp.route("/api/voice/stt_status", methods=["GET"])
def voice_stt_status():
    """Return status for the supported upload-based STT engines."""
    try:
        from app.core.services.local_stt import get_status

        local = get_status()
    except Exception as exc:
        local = {
            "available": False,
            "engine": "unavailable",
            "model": None,
            "error": str(exc),
        }

    return jsonify(
        {
            "local": local,
            "fast": local,
            "cloud": {
                "available": False,
                "engine": "unavailable",
                "reason": "当前 DeepSeek 云模型不支持音频转写",
            },
            "active": local.get("engine") if local.get("available") else "unavailable",
        }
    )


@voice_bp.route("/api/voice/stt", methods=["POST"])
def voice_stt():
    """Transcribe uploaded audio bytes with the local Whisper runtime."""
    try:
        data = request.get_json(silent=True) or {}
        audio_b64 = data.get("audio", "")
        mime_type = data.get("mime", "audio/webm")

        if not audio_b64:
            return jsonify({"success": False, "text": "", "message": "缺少 audio 字段"}), 400

        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception:
            return jsonify({"success": False, "text": "", "message": "音频 base64 解码失败"}), 400

        if len(audio_bytes) < 300:
            return jsonify({"success": False, "text": "", "message": "录音太短，请重新说话"})

        _logger.debug("[STT] uploaded audio %.1fKB MIME=%s", len(audio_bytes) / 1024, mime_type)

        try:
            from app.core.services.local_stt import is_available, transcribe

            if is_available():
                ok, text, engine = transcribe(audio_bytes, mime_type)
                return jsonify(
                    {
                        "success": bool(ok and text),
                        "text": text if ok else "",
                        "engine": engine,
                        "message": "识别成功（本地）" if ok and text else "未检测到语音",
                    }
                )
        except Exception as exc:
            _logger.debug("[STT] local STT unavailable: %s", exc)

        return (
            jsonify(
                {
                    "success": False,
                    "text": "",
                    "engine": "unavailable",
                    "message": (
                        "当前云模型不支持音频转写。请安装 faster-whisper 启用本地语音识别。"
                    ),
                }
            ),
            503,
        )
    except Exception as exc:
        return jsonify({"success": False, "text": "", "message": f"STT 失败: {str(exc)[:200]}"}), 500


@voice_bp.route("/api/speech/extract-actions", methods=["POST"])
def speech_extract_actions():
    """Extract meeting summary, decisions, and action items from text."""
    try:
        data = request.json or {}
        transcript = (data.get("text") or "").strip()
        if len(transcript) < 30:
            return jsonify({"success": False, "error": "缺少有效会议文本"}), 400

        prompt = f"""
你是会议纪要分析助手。请从下面的会议文本中提取结构化结果，仅输出 JSON，不要输出任何额外文字。

输出 JSON schema:
{{
  "summary": "一句到三句会议摘要",
  "decisions": ["决策1", "决策2"],
  "action_items": [
    {{
      "task": "具体可执行任务",
      "owner": "负责人，未知则写待定",
      "due_date": "YYYY-MM-DD 或 待定",
      "priority": "high|medium|low"
    }}
  ]
}}

要求：
1) 不要杜撰；没有提到的负责人/截止日写"待定"。
2) action_items 必须是可执行动作，避免空泛描述。
3) decisions 最多 6 条，action_items 最多 12 条。
4) 语言使用中文。

会议文本：
{transcript[:25000]}
"""
        from app.core.llm.model_selection import (
            get_configured_cloud_model,
            get_configured_cloud_provider,
        )
        from app.core.llm.provider_factory import get_llm_provider

        provider_name = get_configured_cloud_provider()
        model_id = get_configured_cloud_model(provider=provider_name)
        provider = get_llm_provider(provider=provider_name, model=model_id)
        resp = provider.generate_content(
            prompt=prompt,
            model=model_id,
            temperature=0.2,
            max_tokens=1800,
            response_format={"type": "json_object"},
        )
        if isinstance(resp, dict):
            raw = str(resp.get("content") or resp.get("text") or "").strip()
        else:
            raw = str(getattr(resp, "text", resp) or "").strip()
        if raw.startswith("```json"):
            raw = raw[7:].rstrip("`").strip()
        elif raw.startswith("```"):
            raw = raw[3:].rstrip("`").strip()

        parsed = json.loads(raw)
        decisions = parsed.get("decisions") if isinstance(parsed.get("decisions"), list) else []
        actions = parsed.get("action_items") if isinstance(parsed.get("action_items"), list) else []

        cleaned_actions = []
        for item in actions[:12]:
            if not isinstance(item, dict):
                continue
            task = str(item.get("task") or "").strip()
            if not task:
                continue
            priority = str(item.get("priority") or "medium").strip().lower()
            if priority not in {"high", "medium", "low"}:
                priority = "medium"
            cleaned_actions.append(
                {
                    "task": task,
                    "owner": str(item.get("owner") or "待定").strip() or "待定",
                    "due_date": str(item.get("due_date") or "待定").strip() or "待定",
                    "priority": priority,
                }
            )

        return jsonify(
            {
                "success": True,
                "summary": str(parsed.get("summary") or "").strip(),
                "decisions": [str(item).strip() for item in decisions[:6] if str(item).strip()],
                "action_items": cleaned_actions,
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
