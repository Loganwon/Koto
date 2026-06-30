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


def _get_client():
    from web.runtime_context import get_client_proxy

    return get_client_proxy()


def _get_types():
    from web.runtime_context import get_types

    return get_types()


@voice_bp.route("/api/voice/stt_status", methods=["GET"])
def voice_stt_status():
    """Return status for the supported upload-based STT engines."""
    try:
        from web.local_stt import get_status

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
            "gemini": {"available": True, "engine": "gemini-2.5-flash-lite"},
            "active": local.get("engine") if local.get("available") else "gemini",
        }
    )


@voice_bp.route("/api/voice/gemini_stt", methods=["POST"])
@voice_bp.route("/api/voice/stt", methods=["POST"])
def voice_gemini_stt():
    """Transcribe uploaded audio bytes using local Whisper first, then Gemini."""
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
            from web.local_stt import is_available, transcribe

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
            _logger.debug("[STT] local STT unavailable, falling back to Gemini: %s", exc)

        client = _get_client()
        types = _get_types()
        if client is None:
            return (
                jsonify(
                    {
                        "success": False,
                        "text": "",
                        "message": "Gemini 客户端未初始化，请检查 API Key；或安装 faster-whisper 使用本地识别",
                    }
                ),
                503,
            )

        stt_model = "gemini-2.5-flash-lite"
        prompt_parts = [
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            types.Part.from_text(
                text=(
                    "请将上面音频中的语音内容完整转写为文字。"
                    "只输出转写结果，不要加解释、前缀或额外说明。"
                    "如果听不清或没有语音，只输出空字符串。"
                )
            ),
        ]
        resp = client.models.generate_content(
            model=stt_model,
            contents=[types.Content(role="user", parts=prompt_parts)],
            config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=512),
        )

        text = (resp.text or "").strip()
        for prefix in ("转写：", "转写:", "识别：", "识别:", "文字：", "文字:"):
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()

        return jsonify(
            {
                "success": bool(text),
                "text": text,
                "engine": f"Gemini/{stt_model}",
                "message": "识别成功" if text else "未检测到语音内容",
            }
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
        client = _get_client()
        types = _get_types()
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=1800),
        )
        raw = (resp.text or "").strip()
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
