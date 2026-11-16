# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Canonical read-only access to the configured local-model runtime state."""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import time

import requests

logger = logging.getLogger(__name__)

_OLLAMA_API_BASE = "http://127.0.0.1:11434"
_NO_PROXY = {"http": None, "https": None}


def get_configured_local_model_tag() -> str:
    """Return the user-selected Ollama model tag, or an empty string."""
    try:
        from app.core.config.user_settings import SettingsManager

        settings = SettingsManager().get_all()
        return str(
            settings.get("local_model")
            or settings.get("local_model_tag")
            or (settings.get("ai") or {}).get("local_model")
            or (settings.get("ai") or {}).get("local_model_tag")
            or ""
        ).strip()
    except Exception:
        return ""


def get_configured_model_mode() -> str:
    """Return the persisted inference mode in the shared ``cloud``/``local`` form.

    Older releases persisted provider names such as ``deepseek`` and ``ollama``.
    They describe the same two user-visible choices, but exposing them to each
    caller made the chat panel, file tasks, and settings disagree about which
    model was active.  Keep the compatibility read here and give every runtime
    consumer one canonical value.
    """
    try:
        from app.core.config.user_settings import SettingsManager

        stored = (
            str(SettingsManager().get_all().get("model_mode") or "cloud")
            .strip()
            .lower()
        )
        return "local" if stored in {"local", "ollama"} else "cloud"
    except Exception:
        return "cloud"


class OllamaRuntime:
    """Small Ollama transport used for explicit local mode and cloud fallback.

    This runtime deliberately does not inspect natural language, classify tasks,
    or decide whether a request should use local inference.
    """

    RESPONSE_MODEL_PREFERENCE = (
        "qwen3:8b",
        "qwen2.5:14b",
        "gemma3:12b",
        "qwen2.5:7b",
        "qwen3:4b",
        "gemma3:4b",
        "llama3.2:3b",
        "qwen3:1.7b",
        "gemma3:1b",
    )

    _available: bool | None = None
    _check_time = 0.0
    _response_model: str | None = None
    _response_model_inited = False

    @classmethod
    def is_available(cls) -> bool:
        if os.environ.get("KOTO_DEPLOY_MODE") == "cloud":
            cls._available = False
            return False
        if cls._available is not None and time.time() - cls._check_time < 30:
            return cls._available
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.1)
            cls._available = sock.connect_ex(("127.0.0.1", 11434)) == 0
        except OSError as exc:
            logger.debug("Ollama socket check failed: %s", exc)
            cls._available = False
        finally:
            if sock is not None:
                sock.close()
            cls._check_time = time.time()
        return bool(cls._available)

    @classmethod
    def _installed_models(cls) -> list[str]:
        if not cls.is_available():
            return []
        try:
            response = requests.get(
                f"{_OLLAMA_API_BASE}/api/tags", timeout=2, proxies=_NO_PROXY
            )
            if response.status_code != 200:
                return []
            return [
                str(item.get("name") or "").strip()
                for item in response.json().get("models", [])
                if str(item.get("name") or "").strip()
            ]
        except requests.RequestException as exc:
            logger.debug("Unable to list Ollama models: %s", exc)
            return []

    @classmethod
    def pick_best_chat_model(cls, installed_models: list[str] | None = None) -> str:
        installed = (
            list(installed_models)
            if installed_models is not None
            else cls._installed_models()
        )
        for preferred in cls.RESPONSE_MODEL_PREFERENCE:
            preferred_base = preferred.split(":", 1)[0]
            for name in installed:
                if name == preferred or name.split(":", 1)[0] == preferred_base:
                    return name
        return installed[0] if installed else ""

    @classmethod
    def reset_response_model(cls) -> None:
        cls._response_model = None
        cls._response_model_inited = False

    @classmethod
    def _init_response_model(cls) -> bool:
        if cls._response_model_inited and cls._response_model:
            return True
        installed = cls._installed_models()
        if not installed:
            return False

        configured = get_configured_local_model_tag()
        if configured:
            if configured not in installed:
                logger.warning(
                    "Configured Ollama model is not installed: %s", configured
                )
                return False
            selected = configured
        else:
            selected = cls.pick_best_chat_model(installed)
        if not selected:
            return False
        cls._response_model = selected
        cls._response_model_inited = True
        logger.info("Using Ollama response model: %s", selected)
        return True

    @classmethod
    def call_chat(
        cls,
        messages: list,
        model_name: str | None = None,
        fmt: str | None = None,
        options: dict | None = None,
        timeout: float = 10.0,
        strip_think: bool = True,
    ) -> tuple[str, str | None]:
        selected = model_name or get_configured_local_model_tag()
        if not selected:
            if not cls._init_response_model():
                return "", "❌ 无可用本地模型"
            selected = cls._response_model
        payload = {"model": selected, "messages": messages, "stream": False}
        if fmt:
            payload["format"] = fmt
            payload["think"] = False
        if options:
            payload["options"] = options
        try:
            response = requests.post(
                f"{_OLLAMA_API_BASE}/api/chat",
                json=payload,
                timeout=timeout,
                proxies=_NO_PROXY,
            )
            if response.status_code != 200:
                return "", f"❌ HTTP {response.status_code}: {response.text[:120]}"
            data = response.json()
            content = str(
                (data.get("message") or {}).get("content") or data.get("response") or ""
            ).strip()
            if strip_think and content:
                content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
            return content, None
        except requests.exceptions.Timeout:
            return "", f"⏱️ 超时 ({timeout}s)"
        except requests.RequestException as exc:
            return "", f"❌ 请求失败: {exc}"

    @classmethod
    def generate_stream(
        cls,
        user_input: str,
        history: list | None = None,
        system_instruction: str | None = None,
        timeout: float = 30.0,
    ):
        if not cls._init_response_model():
            return None
        messages = [
            {
                "role": "system",
                "content": system_instruction
                or (
                    "你是 Koto，一个友善、专业的 AI 助手。用中文回答中文问题，"
                    "用英文回答英文问题；回答简洁、准确，不确定时如实说明。"
                ),
            }
        ]
        for turn in list(history or [])[-8:]:
            role = (
                "assistant" if turn.get("role") == "model" else turn.get("role", "user")
            )
            parts = turn.get("parts", [])
            content = " ".join(str(part) for part in parts).strip()
            if content:
                messages.append({"role": role, "content": content[:500]})
        messages.append({"role": "user", "content": user_input})

        def _stream():
            try:
                response = requests.post(
                    f"{_OLLAMA_API_BASE}/api/chat",
                    json={
                        "model": cls._response_model,
                        "messages": messages,
                        "stream": True,
                        "options": {"temperature": 0.7, "num_predict": 2048},
                    },
                    stream=True,
                    timeout=timeout,
                    proxies=_NO_PROXY,
                )
                if response.status_code != 200:
                    return
                in_think = False
                buffer = ""
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    content = str((data.get("message") or {}).get("content") or "")
                    if content:
                        buffer += content
                        while buffer:
                            if in_think:
                                end = buffer.find("</think>")
                                if end < 0:
                                    buffer = ""
                                    break
                                buffer = buffer[end + 8 :]
                                in_think = False
                            else:
                                start = buffer.find("<think>")
                                if start >= 0:
                                    if start:
                                        yield buffer[:start]
                                    buffer = buffer[start + 7 :]
                                    in_think = True
                                elif len(buffer) > 10:
                                    yield buffer[:-10]
                                    buffer = buffer[-10:]
                                else:
                                    break
                    if data.get("done"):
                        if buffer and not in_think:
                            yield buffer
                        break
            except requests.RequestException as exc:
                logger.error("Ollama stream failed: %s", exc)

        return _stream()


__all__ = [
    "OllamaRuntime",
    "get_configured_local_model_tag",
    "get_configured_model_mode",
]
