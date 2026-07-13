"""Local-routing fallback used by the chat runtime."""

from __future__ import annotations

import os

from app.core.routing.smart_dispatcher import SmartDispatcher

LOCAL_ROUTER_MODEL = "qwen3.5:9b"
OLLAMA_API_URL = "http://127.0.0.1:11434/api/generate"


class LocalDispatcher:
    """Fallback router backed by a fast Ollama availability probe."""

    @staticmethod
    def is_ollama_running() -> bool:
        if os.environ.get("KOTO_DEPLOY_MODE") == "cloud":
            return False
        try:
            import requests

            requests.get(
                "http://127.0.0.1:11434",
                timeout=0.5,
                proxies={"http": None, "https": None},
            )
            return True
        except Exception:
            return False

    @staticmethod
    def analyze(user_input, history=None):
        return SmartDispatcher.analyze(user_input, history)
