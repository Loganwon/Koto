# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import json

from flask import Flask


def _client():
    from web.blueprints.voice import voice_bp

    app = Flask(__name__)
    app.register_blueprint(voice_bp)
    app.config["TESTING"] = True
    return app.test_client()


def test_voice_status_does_not_advertise_archived_cloud_stt(monkeypatch):
    import app.core.services.local_stt as local_stt

    monkeypatch.setattr(
        local_stt,
        "get_status",
        lambda: {"available": False, "engine": "unavailable", "model": None},
    )

    response = _client().get("/api/voice/stt_status")
    payload = response.get_json()

    assert response.status_code == 200
    assert "gemini" not in payload
    assert payload["cloud"]["available"] is False
    assert payload["active"] == "unavailable"


def test_voice_upload_returns_actionable_error_without_local_stt(monkeypatch):
    import app.core.services.local_stt as local_stt

    monkeypatch.setattr(local_stt, "is_available", lambda: False)
    audio = base64.b64encode(b"x" * 512).decode()

    response = _client().post(
        "/api/voice/stt", json={"audio": audio, "mime": "audio/webm"}
    )

    assert response.status_code == 503
    assert "faster-whisper" in response.get_json()["message"]


def test_meeting_extraction_uses_active_text_provider(monkeypatch):
    import app.core.llm.provider_factory as provider_factory

    class _Provider:
        def generate_content(self, **kwargs):
            return {
                "content": json.dumps(
                    {
                        "summary": "会议确认上线计划。",
                        "decisions": ["周五上线"],
                        "action_items": [
                            {
                                "task": "完成回归测试",
                                "owner": "小王",
                                "due_date": "2026-07-17",
                                "priority": "high",
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            }

    monkeypatch.setattr(
        provider_factory, "get_llm_provider", lambda **kwargs: _Provider()
    )
    transcript = "会议讨论了上线计划。" * 10

    response = _client().post("/api/speech/extract-actions", json={"text": transcript})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["decisions"] == ["周五上线"]
    assert payload["action_items"][0]["task"] == "完成回归测试"


def test_audio_overview_dependency_is_part_of_runtime():
    from web.audio_overview import AudioOverviewGenerator

    assert AudioOverviewGenerator.VOICE_HOST_A.startswith("zh-CN-")
