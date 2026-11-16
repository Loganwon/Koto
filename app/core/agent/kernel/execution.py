from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .catalog import ToolCatalog
from .contracts import TRUSTED_CONTEXT_ARGUMENT, ToolCall, ToolErrorCode, ToolResult


@dataclass(frozen=True)
class ToolExecutionPolicy:
    default_timeout_seconds: float = 60.0
    timeout_overrides: Mapping[str, float] = field(default_factory=dict)
    max_concurrency: int = 8

    def __post_init__(self) -> None:
        if float(self.default_timeout_seconds) <= 0:
            raise ValueError("default_timeout_seconds must be positive")
        if int(self.max_concurrency) < 1:
            raise ValueError("max_concurrency must be positive")

    def timeout_for(self, tool_name: str, spec_timeout: Optional[float]) -> float:
        if spec_timeout is not None:
            return float(spec_timeout)
        override = self.timeout_overrides.get(tool_name)
        if override is not None:
            return float(override)
        return float(self.default_timeout_seconds)


class ToolExecutor:
    """Single execution boundary used by core tools and future plugins."""

    def __init__(
        self,
        catalog: ToolCatalog,
        policy: Optional[ToolExecutionPolicy] = None,
    ) -> None:
        self._catalog = catalog
        self._policy = policy or ToolExecutionPolicy()
        self._capacity = threading.BoundedSemaphore(
            max(1, int(self._policy.max_concurrency))
        )

    def invoke(
        self,
        call: ToolCall,
        *,
        invocation_context: Any = None,
    ) -> ToolResult:
        started = time.monotonic()
        spec = self._catalog.get(call.name)
        if spec is None:
            return self._failure(
                call,
                ToolErrorCode.NOT_FOUND,
                f"Tool '{call.name}' not found.",
                started,
            )

        if TRUSTED_CONTEXT_ARGUMENT in call.arguments:
            return self._policy_denied(
                call,
                spec,
                reason="model_context_injection",
                message="Trusted tool context cannot be supplied by model arguments.",
                invocation_context=invocation_context,
                started=started,
            )
        if spec.requires_invocation_context:
            require_identity = getattr(invocation_context, "require_identity", None)
            if not callable(require_identity):
                return self._policy_denied(
                    call,
                    spec,
                    reason="trusted_context_missing",
                    message=f"Tool '{call.name}' requires a trusted host identity.",
                    invocation_context=invocation_context,
                    started=started,
                )
            try:
                require_identity()
            except Exception:
                return self._policy_denied(
                    call,
                    spec,
                    reason="trusted_context_invalid",
                    message=(
                        f"Tool '{call.name}' requires a valid trusted host identity."
                    ),
                    invocation_context=invocation_context,
                    started=started,
                )

        try:
            Draft202012Validator(spec.input_schema).validate(dict(call.arguments))
        except ValidationError as exc:
            location = ".".join(str(item) for item in exc.absolute_path)
            detail = f" at '{location}'" if location else ""
            return self._failure(
                call,
                ToolErrorCode.INVALID_ARGUMENTS,
                f"Invalid arguments for tool '{call.name}'{detail}: {exc.message}",
                started,
            )

        timeout = self._policy.timeout_for(call.name, spec.timeout_seconds)
        if not self._capacity.acquire(timeout=timeout):
            return self._failure(
                call,
                ToolErrorCode.TIMEOUT,
                f"Tool '{call.name}' could not start within {timeout:g}s",
                started,
            )

        # A Python thread cannot be killed safely.  Returning TIMEOUT while a
        # mutating handler keeps running creates an unknowable external state
        # and makes retries dangerous.  Explicitly mutating in-process tools
        # therefore complete synchronously; read-only tools may abandon a late
        # result because they cannot commit a side effect.
        if spec.read_only is False:
            try:
                value = spec.handler(
                    **self._handler_arguments(
                        call,
                        requires_context=spec.requires_invocation_context,
                        invocation_context=invocation_context,
                    )
                )
            except TypeError as exc:
                return self._failure(
                    call,
                    ToolErrorCode.INVALID_ARGUMENTS,
                    f"Argument mismatch for tool '{call.name}': {exc}",
                    started,
                )
            except Exception as exc:
                return self._failure(
                    call,
                    ToolErrorCode.EXECUTION_ERROR,
                    f"Error executing tool '{call.name}': {exc}",
                    started,
                )
            finally:
                self._capacity.release()
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                ok=True,
                value=value,
                duration_ms=self._duration_ms(started),
            )

        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="koto-tool")

        def _run_read_only():
            try:
                return spec.handler(
                    **self._handler_arguments(
                        call,
                        requires_context=spec.requires_invocation_context,
                        invocation_context=invocation_context,
                    )
                )
            finally:
                self._capacity.release()

        future = pool.submit(_run_read_only)
        try:
            value = future.result(timeout=timeout)
        except FuturesTimeout:
            future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            return self._failure(
                call,
                ToolErrorCode.TIMEOUT,
                f"Tool '{call.name}' timed out after {timeout:g}s",
                started,
            )
        except TypeError as exc:
            pool.shutdown(wait=True)
            return self._failure(
                call,
                ToolErrorCode.INVALID_ARGUMENTS,
                f"Argument mismatch for tool '{call.name}': {exc}",
                started,
            )
        except Exception as exc:
            pool.shutdown(wait=True)
            return self._failure(
                call,
                ToolErrorCode.EXECUTION_ERROR,
                f"Error executing tool '{call.name}': {exc}",
                started,
            )
        else:
            pool.shutdown(wait=True)
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                ok=True,
                value=value,
                duration_ms=self._duration_ms(started),
            )

    def invoke_many(
        self,
        calls: Sequence[ToolCall],
        *,
        max_workers: int = 6,
        invocation_context: Any = None,
    ) -> list[ToolResult]:
        """Execute a tool batch safely and preserve the model's call order.

        Parallel execution is only valid when every tool explicitly declares
        itself read-only. Unknown or mutating tools are serialized because two
        writes in one model turn may target the same file or external resource.
        """

        pending = list(calls)
        if not pending:
            return []
        if len(pending) == 1:
            return [self.invoke(pending[0], invocation_context=invocation_context)]

        specs = [self._catalog.get(call.name) for call in pending]
        if not all(spec is not None and spec.read_only is True for spec in specs):
            return [
                self.invoke(call, invocation_context=invocation_context)
                for call in pending
            ]

        workers = max(1, min(int(max_workers or 1), len(pending)))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="koto-tool-batch"
        ) as pool:
            futures = [
                pool.submit(
                    self.invoke,
                    call,
                    invocation_context=invocation_context,
                )
                for call in pending
            ]
            return [future.result() for future in futures]

    @staticmethod
    def _handler_arguments(
        call: ToolCall,
        *,
        requires_context: bool,
        invocation_context: Any,
    ) -> dict[str, Any]:
        arguments = dict(call.arguments)
        if requires_context:
            arguments[TRUSTED_CONTEXT_ARGUMENT] = invocation_context
        return arguments

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, round((time.monotonic() - started) * 1000))

    def _failure(
        self,
        call: ToolCall,
        code: ToolErrorCode,
        message: str,
        started: float,
    ) -> ToolResult:
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.name,
            ok=False,
            error_code=code,
            error_message=message,
            duration_ms=self._duration_ms(started),
        )

    def _policy_denied(
        self,
        call: ToolCall,
        spec: Any,
        message: str,
        started: float,
        *,
        reason: str,
        invocation_context: Any,
    ) -> ToolResult:
        callback = getattr(spec, "policy_denied_handler", None)
        if callable(callback):
            try:
                callback(reason, invocation_context)
            except Exception:
                pass
        return self._failure(
            call,
            ToolErrorCode.POLICY_DENIED,
            message,
            started,
        )
