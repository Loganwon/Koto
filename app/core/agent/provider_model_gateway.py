"""Adapters from Koto LLM providers to the Agent Kernel model protocol."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from app.core.agent.kernel import ModelResponse
from app.core.agent.kernel.model import iter_model_stream


class ProviderModelGateway:
    """One model-call boundary shared by production Agent entrypoints."""

    def __init__(
        self,
        provider: Any,
        *,
        task_type: str = "AGENT",
        allow_fallback: bool = True,
    ) -> None:
        self._provider = provider
        self._task_type = str(task_type or "AGENT")
        self._allow_fallback = bool(allow_fallback)

    def context_options(self, options=None):
        resolver = getattr(self._provider, "context_options", None)
        return resolver(options) if callable(resolver) else dict(options or {})

    def generate(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        system: str,
        tools: Sequence[Mapping[str, Any]],
        model_id: str = "",
        options: Optional[Mapping[str, Any]] = None,
    ) -> ModelResponse:
        call_options = dict(options or {})
        task_type = str(
            call_options.pop("task_type", self._task_type) or self._task_type
        )
        session_id = call_options.pop("session_id", None)
        call_options.pop("stream", None)
        for key in (
            "context_window_tokens",
            "context_window",
            "reserved_output_tokens",
            "addon_tool_names",
            "_cancel_check",
        ):
            call_options.pop(key, None)

        if self._allow_fallback:
            try:
                from app.core.llm.model_fallback import get_fallback_executor

                raw = get_fallback_executor().generate_with_fallback(
                    provider=self._provider,
                    prompt=list(messages),
                    preferred_model=model_id,
                    task_type=task_type,
                    system_instruction=system,
                    tools=list(tools) if tools else None,
                    stream=False,
                    session_id=session_id,
                    **call_options,
                )
                return ModelResponse.from_raw(raw, strict=False)
            except ImportError:
                pass

        raw = self._provider.generate_content(
            prompt=list(messages),
            model=model_id,
            system_instruction=system,
            tools=list(tools) if tools else None,
            stream=False,
            session_id=session_id,
            **call_options,
        )
        return ModelResponse.from_raw(raw, strict=False)

    def generate_stream(self, *, messages, system, tools, model_id="", options=None):
        """Stream one model turn without replaying partially emitted output.

        Provider fallback remains available before any visible text. Once a
        stream starts, a failure belongs to that attempt and must not silently
        concatenate another model's answer or rerun a tool call.
        """
        if tools and getattr(self._provider, "streaming_tool_calls", True) is False:
            yield from iter_model_stream(
                self.generate(
                    messages=messages,
                    system=system,
                    tools=tools,
                    model_id=model_id,
                    options=options,
                )
            )
            return
        call_options = dict(options or {})
        call_options.pop("stream", None)
        task_type = str(
            call_options.pop("task_type", self._task_type) or self._task_type
        )
        call_options.pop("addon_tool_names", None)
        for key in (
            "context_window_tokens",
            "context_window",
            "reserved_output_tokens",
        ):
            call_options.pop(key, None)
        try:
            executor = None
            if self._allow_fallback:
                try:
                    from app.core.llm.model_fallback import get_fallback_executor

                    executor = get_fallback_executor()
                except ImportError:
                    pass
            if executor is not None:
                raw = executor.generate_with_fallback(
                    provider=self._provider,
                    prompt=list(messages),
                    preferred_model=model_id,
                    task_type=task_type,
                    system_instruction=system,
                    tools=list(tools) if tools else None,
                    stream=True,
                    **call_options,
                )
            else:
                raw = self._provider.generate_content(
                    prompt=list(messages),
                    model=model_id,
                    system_instruction=system,
                    tools=list(tools) if tools else None,
                    stream=True,
                    **call_options,
                )
        except (NotImplementedError, TypeError):
            # Older injected providers can implement only the original API.
            yield from iter_model_stream(
                self.generate(
                    messages=messages,
                    system=system,
                    tools=tools,
                    model_id=model_id,
                    options=options,
                )
            )
            return
        yield from iter_model_stream(raw)


__all__ = ["ProviderModelGateway"]
