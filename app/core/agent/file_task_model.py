from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from app.core.agent.file_task_contract import FileTaskRequest
from app.core.llm.model_mode import normalize_model_mode

logger = logging.getLogger(__name__)

_DEFAULT_FILE_TASK_MODEL = "gemini-3-flash-preview"
_FILE_TASK_LLM_CALL_TIMEOUT = float(os.getenv("KOTO_FILE_TASK_LLM_TIMEOUT", "45"))


class FileTaskModelClient:
    """Small adapter for file-task model calls across cloud and local providers."""

    def __init__(
        self,
        *,
        api_key: str = "",
        default_model: str = "",
    ):
        self._api_key = api_key
        self._default_model = default_model or _DEFAULT_FILE_TASK_MODEL

    def call(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return self._call_native(request=request, messages=messages, system=system, tools=tools)

    def _call_native(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        mode = normalize_model_mode(request.model_mode, default="cloud")
        if mode == "local":
            return self._call_local(request=request, messages=messages, system=system, tools=tools)

        try:
            return self._call_cloud(request=request, messages=messages, system=system, tools=tools)
        except Exception as exc:
            if not bool(request.options.get("allow_local_fallback", True)):
                raise
            # API-layer errors (auth, quota, bad-request) should not trigger a
            # local fallback — the cloud is reachable but refusing the request.
            if self._is_api_layer_error(exc):
                raise
            if not self._is_local_available():
                raise
            logger.warning(
                "[FileTaskModelClient] cloud call failed (network/timeout), falling back to local model: %s",
                exc,
            )
            return self._call_local(request=request, messages=messages, system=system, tools=tools)

    @staticmethod
    def _is_api_layer_error(exc: Exception) -> bool:
        """Return True for errors that indicate the cloud API is reachable but
        refusing the request (e.g. invalid key, quota exceeded, bad request).
        These should NOT trigger a local-model fallback."""
        msg = str(exc).lower()
        api_signals = ("401", "403", "429", "invalid api key", "permission denied", "quota exceeded", "rate limit")
        return any(s in msg for s in api_signals)

    def _call_cloud(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        from app.core.llm.gemini import GeminiProvider

        api_key = self._api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("No Gemini API key configured")

        provider = GeminiProvider(api_key=api_key)
        model_id = self._cloud_model_id(request)
        try:
            from app.core.llm.model_fallback import get_fallback_executor

            executor = get_fallback_executor()
            return executor.generate_with_fallback(
                provider=provider,
                prompt=messages,
                preferred_model=model_id,
                task_type="FILE_TASK",
                system_instruction=system,
                tools=tools if tools else None,
                stream=False,
                call_timeout=_FILE_TASK_LLM_CALL_TIMEOUT,
                temperature=0.2,
            )
        except ImportError:
            return provider.generate_content(
                prompt=messages,
                model=model_id,
                system_instruction=system,
                tools=tools if tools else None,
                stream=False,
                call_timeout=_FILE_TASK_LLM_CALL_TIMEOUT,
                temperature=0.2,
            )

    def _call_local(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self._is_local_available():
            raise RuntimeError("Local Ollama is not reachable")
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        model_id = self._local_model_id(request)
        logger.info(
            "[FileTaskModelClient] local file-task call model=%s messages=%d tools=%d timeout=%.1fs",
            model_id or "<auto>",
            len(messages),
            len(tools or []),
            _FILE_TASK_LLM_CALL_TIMEOUT,
        )
        provider = OllamaLLMProvider(model=model_id or None)
        return provider.generate_content(
            prompt=messages,
            model=model_id or None,
            system_instruction=system,
            tools=tools if tools else None,
            stream=False,
            call_timeout=_FILE_TASK_LLM_CALL_TIMEOUT,
            temperature=0.2,
        )

    def _cloud_model_id(self, request: FileTaskRequest) -> str:
        requested = str(request.model_id or "").strip()
        if requested and requested.lower() not in {"auto", "cloud", "local"}:
            return requested
        try:
            from web.app import MODEL_MAP  # type: ignore

            for task_key in ("FILE_TASK", "CHAT"):
                model_from_app = str(MODEL_MAP.get(task_key) or "").strip()
                if model_from_app:
                    return model_from_app
        except Exception:
            pass
        return self._default_model

    def _local_model_id(self, request: FileTaskRequest) -> str:
        configured = str(request.options.get("local_model") or request.model_id or "").strip()
        if configured.lower().startswith("gemini") or configured.lower() in {"auto", "cloud", "local"}:
            return ""
        return configured

    def _is_local_available(self) -> bool:
        try:
            from app.core.shared.llm_helpers import is_ollama_alive

            return bool(is_ollama_alive())
        except Exception:
            return False