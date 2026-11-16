"""Provider-neutral final-response validation for the Agent Kernel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Tuple, runtime_checkable

from .lifecycle import AgentRequest


@dataclass(frozen=True)
class ValidationOutcome:
    """One deterministic decision about a model's proposed final response."""

    accepted: bool
    content: str
    retry_instruction: str = ""
    blocked: bool = False
    reasons: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.accepted and self.retry_instruction:
            raise ValueError("accepted validation outcome cannot request a retry")
        if self.blocked and self.accepted:
            raise ValueError("blocked validation outcome cannot be accepted")
        if not self.accepted and not self.blocked and not self.retry_instruction:
            raise ValueError(
                "rejected validation outcome requires retry_instruction or blocked=True"
            )

    @classmethod
    def accept(
        cls, content: str, *, reasons: Tuple[str, ...] = ()
    ) -> "ValidationOutcome":
        return cls(accepted=True, content=str(content or ""), reasons=reasons)

    @classmethod
    def retry(
        cls,
        content: str,
        instruction: str,
        *,
        reasons: Tuple[str, ...] = (),
    ) -> "ValidationOutcome":
        return cls(
            accepted=False,
            content=str(content or ""),
            retry_instruction=str(instruction or "").strip(),
            reasons=reasons,
        )

    @classmethod
    def block(
        cls, content: str, *, reasons: Tuple[str, ...] = ()
    ) -> "ValidationOutcome":
        return cls(
            accepted=False,
            content=str(content or ""),
            blocked=True,
            reasons=reasons,
        )


@runtime_checkable
class ResponseValidator(Protocol):
    """Validation boundary used after the model proposes a final response."""

    def validate(self, content: str, request: AgentRequest) -> ValidationOutcome: ...


__all__ = ["ResponseValidator", "ValidationOutcome"]
