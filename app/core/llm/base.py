# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional, Union

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    Standardizes the interface for OpenAI, Google Gemini, Anthropic, Ollama, etc.
    """

    def _log_request(self, prompt: Union[str, List], model: str) -> None:
        """
        Log an outgoing LLM request at DEBUG level.
        Concrete subclasses should call this at the start of generate_content().
        """
        prompt_len = len(prompt) if isinstance(prompt, str) else len(prompt)
        logger.debug(
            "[LLMProvider] generate_content model=%s prompt_len=%d class=%s",
            model,
            prompt_len,
            type(self).__name__,
        )

    def _log_response(
        self,
        model: str,
        response_len: int = 0,
        *,
        error: bool = False,
        error_msg: str = "",
    ) -> None:
        """
        Log the result of an LLM call.
        Call with error=True when generate_content raises or returns an error.
        """
        if error:
            logger.warning(
                "[LLMProvider] generate_content ERROR model=%s class=%s: %s",
                model,
                type(self).__name__,
                error_msg,
            )
        else:
            logger.debug(
                "[LLMProvider] generate_content OK model=%s response_len=%d class=%s",
                model,
                response_len,
                type(self).__name__,
            )

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _extract_usage_value(
        self, usage: Any, field_names: tuple[str, ...], depth: int = 0
    ) -> int:
        if usage is None or depth > 2:
            return 0

        if isinstance(usage, dict):
            for name in field_names:
                if name in usage:
                    return self._safe_int(usage.get(name))
            for nested_name in ("usage", "usage_metadata", "metadata", "token_usage"):
                if nested_name in usage:
                    value = self._extract_usage_value(
                        usage.get(nested_name), field_names, depth + 1
                    )
                    if value:
                        return value
            return 0

        for name in field_names:
            if hasattr(usage, name):
                return self._safe_int(getattr(usage, name, 0))

        for nested_name in ("usage", "usage_metadata", "metadata", "token_usage"):
            nested = getattr(usage, nested_name, None)
            value = self._extract_usage_value(nested, field_names, depth + 1)
            if value:
                return value
        return 0

    def _normalize_usage(self, usage: Any) -> Dict[str, int]:
        if not usage:
            return {}

        prompt_tokens = self._extract_usage_value(
            usage,
            (
                "prompt_tokens",
                "prompt_token_count",
                "input_tokens",
                "input_token_count",
            ),
        )
        completion_tokens = self._extract_usage_value(
            usage,
            (
                "completion_tokens",
                "candidates_token_count",
                "output_tokens",
                "output_token_count",
            ),
        )

        if not prompt_tokens and not completion_tokens:
            return {}

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

    def _track_usage(
        self,
        model: str,
        usage: Any,
        *,
        skill_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        normalized = self._normalize_usage(usage)
        if not normalized:
            return

        try:
            import app.core.analytics.token_tracker as token_tracker

            if skill_id or session_id:
                token_tracker.record_usage_with_skill(
                    model=model,
                    prompt_tokens=normalized["prompt_tokens"],
                    completion_tokens=normalized["completion_tokens"],
                    skill_id=skill_id,
                    session_id=session_id,
                )
            else:
                token_tracker.record_usage(
                    model=model,
                    prompt_tokens=normalized["prompt_tokens"],
                    completion_tokens=normalized["completion_tokens"],
                )
        except Exception as exc:
            logger.debug(
                "[LLMProvider] token tracking skipped model=%s class=%s: %s",
                model,
                type(self).__name__,
                exc,
            )

    @abstractmethod
    def generate_content(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        model: str,
        system_instruction: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        stream: bool = False,
        **kwargs,
    ) -> Union[Dict[str, Any], Generator[Dict[str, Any], None, None]]:
        """
        Generate content from the LLM.

        Args:
            prompt: The user prompt or list of messages
            model: Model identifier
            system_instruction: System prompt
            tools: List of tool definitions
            stream: Whether to stream the response
            **kwargs: Additional provider-specific arguments (temperature, etc.)

        Returns:
            Structured response dictionary or generator if streaming
        """
        pass

    @abstractmethod
    def get_token_count(
        self, prompt: Union[str, List[Dict[str, Any]]], model: str
    ) -> int:
        """Count tokens for a given prompt/model"""
        pass
