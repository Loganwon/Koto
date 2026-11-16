from __future__ import annotations

import json
import time
from collections import Counter
from typing import Collection, Iterable

from .contracts import AgentRunLimits, ToolCall


class RunLimitExceeded(RuntimeError):
    """The model loop exceeded a deterministic safety budget."""


class RunGuard:
    """Provider-neutral step, call, duration, and duplicate-batch guard."""

    def __init__(self, limits: AgentRunLimits | None = None) -> None:
        self.limits = limits or AgentRunLimits()
        self._started = time.monotonic()
        self._steps = 0
        self._tool_calls = 0
        self._batch_counts: Counter[str] = Counter()
        self._nonrepeatable_calls: set[str] = set()

    def begin_step(self) -> None:
        self._check_time()
        self._steps += 1
        if self._steps > self.limits.max_steps:
            raise RunLimitExceeded("agent step limit exceeded")

    def accept_tool_batch(
        self,
        calls: Iterable[ToolCall],
        *,
        nonrepeatable_names: Collection[str] = (),
    ) -> str:
        self._check_time()
        batch = list(calls)
        self._tool_calls += len(batch)
        if self._tool_calls > self.limits.max_tool_calls:
            raise RunLimitExceeded("agent tool-call limit exceeded")

        nonrepeatable = set(nonrepeatable_names)
        for call in batch:
            if call.name not in nonrepeatable:
                continue
            call_signature = json.dumps(
                {"name": call.name, "arguments": dict(call.arguments)},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            )
            if call_signature in self._nonrepeatable_calls:
                raise RunLimitExceeded("mutating tool call cannot be repeated")
            self._nonrepeatable_calls.add(call_signature)

        signature = json.dumps(
            [{"name": call.name, "arguments": dict(call.arguments)} for call in batch],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        self._batch_counts[signature] += 1
        allowed_occurrences = 1 + self.limits.max_repeated_batches
        if self._batch_counts[signature] > allowed_occurrences:
            raise RunLimitExceeded("repeated identical tool batch")
        return signature

    def _check_time(self) -> None:
        if time.monotonic() - self._started > self.limits.max_seconds:
            raise RunLimitExceeded("agent runtime limit exceeded")
